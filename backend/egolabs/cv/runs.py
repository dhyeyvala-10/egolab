"""
Model runs: model-version registration, creating runs, and chaining them.

A run can take input from other runs of the same video (`CvRun.inputs`): movement classification reads a
hand-tracking run and, if there is one, an object-detection run. A run whose inputs haven't finished waits
(`waiting`); when an input finishes, `input_finished` starts the runs that were waiting on it, or fails them
if the input failed. So one request — hand tracking + object detection + movement — ends with events on the
timeline without anyone starting the last step.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from egolabs.cv import registry
from egolabs.events import record_event
from egolabs.jobs import enqueue_job
from egolabs.models import CvRun, CvRunKind, CvRunStatus, ModelVersion, Video

JOB_TYPES = {
    CvRunKind.hand_tracking: "cv.hand_tracking",
    CvRunKind.object_detection: "cv.object_detection",
    CvRunKind.movement: "cv.movement",
}
LABELS = {
    CvRunKind.hand_tracking: "Hand tracking",
    CvRunKind.object_detection: "Object detection",
    CvRunKind.movement: "Movement classification",
}


class RunRequestError(ValueError):
    pass


def model_version_for(
    db: Session, adapter: Any, name: str, config: dict[str, Any], kind: str = "hand_tracking"
) -> ModelVersion:
    """Get or create the model version for this adapter + config (each distinct setup is its own version)."""
    meta = adapter.metadata()
    version = f"{meta.version} cfg:{registry.config_hash(name, config, kind)}"
    query = select(ModelVersion).where(ModelVersion.name == meta.name, ModelVersion.version == version)
    existing = db.scalar(query)
    if existing:
        return existing
    mv = ModelVersion(name=meta.name, version=version, kind=adapter.kind, adapter=registry.target(name, kind),
                      config=config, keypoint_schema=meta.keypoint_schema,
                      metrics={"labels": meta.labels} if meta.labels else {})  # fmt: skip
    db.add(mv)
    try:
        db.commit()
    except IntegrityError:  # another worker registered it first
        db.rollback()
        mv = db.scalar(query)
        assert mv is not None
    return mv


def latest_succeeded(db: Session, video_id: uuid.UUID, kind: str) -> CvRun | None:
    return db.scalar(
        select(CvRun)
        .where(CvRun.video_id == video_id, CvRun.kind == kind, CvRun.status == CvRunStatus.succeeded)
        .order_by(CvRun.finished_at.desc(), CvRun.id)
        .limit(1)
    )


def _enqueue(db: Session, run: CvRun, user_id: uuid.UUID | None) -> None:
    run.status = CvRunStatus.queued
    db.commit()
    job = enqueue_job(db, JOB_TYPES[CvRunKind(run.kind)], {"run_id": str(run.id)}, created_by=user_id)
    run.job_id = job.id
    db.commit()


def create_runs(
    db: Session,
    video: Video,
    kinds: list[str],
    stride: int,
    user_id: uuid.UUID | None,
    setups: dict[str, tuple[str, dict[str, Any]]] | None = None,
) -> list[CvRun]:
    """
    Queue the requested kinds of run on one video, each with its configured adapter, or the (adapter,
    config) `setups` gives for its kind (e.g. a registered model version's). Movement classification takes
    the hand-tracking and object-detection runs created alongside it, or else the video's latest successful
    ones; it waits until they finish.
    """
    ordered = [k for k in CvRunKind if k.value in kinds]
    created: dict[CvRunKind, CvRun] = {}
    inputs: dict[str, str] = {}
    if CvRunKind.movement in ordered:
        for kind in (CvRunKind.hand_tracking, CvRunKind.object_detection):
            if kind in ordered:
                continue
            prior = latest_succeeded(db, video.id, kind)
            if prior is not None:
                inputs[kind.value] = str(prior.id)
            elif kind == CvRunKind.hand_tracking:
                raise RunRequestError(
                    f"{video.original_filename} has no successful hand-tracking run to classify; "
                    "include hand_tracking in the request"
                )
    for kind in ordered:
        name, config = (setups or {}).get(kind.value) or registry.configured(kind.value)
        run = CvRun(video_id=video.id, kind=kind.value, adapter=name, config=config,
                    stride=stride if kind != CvRunKind.movement else 1, created_by=user_id,
                    frames_total=video.frame_count)  # fmt: skip
        if kind == CvRunKind.movement:
            run.inputs = {**inputs, **{k.value: str(r.id) for k, r in created.items()}}
            run.status = CvRunStatus.waiting
        db.add(run)
        db.commit()
        created[kind] = run
    for kind, run in created.items():
        if kind != CvRunKind.movement or _inputs_ready(db, run) == "ready":
            _enqueue(db, run, user_id)
    return list(created.values())


def _inputs_ready(db: Session, run: CvRun) -> str:
    """'ready' when every input succeeded, 'failed' when one failed, else 'waiting'."""
    states = [db.get(CvRun, uuid.UUID(i)) for i in (run.inputs or {}).values()]
    if any(s is None or s.status == CvRunStatus.failed for s in states):
        return "failed"
    return "ready" if all(s is not None and s.status == CvRunStatus.succeeded for s in states) else "waiting"


def fail(db: Session, run: CvRun, error: str) -> None:
    run.status, run.error, run.finished_at = CvRunStatus.failed, error[:2000], datetime.now(UTC)
    label = LABELS.get(CvRunKind(run.kind), run.kind)
    record_event(db, "cv.run_failed", f"{label} failed: {error}"[:500], entity_type="cv_run",
                 entity_id=run.id, data={"video_id": str(run.video_id), "kind": run.kind})  # fmt: skip


def input_finished(db: Session, run: CvRun) -> None:
    """Start (or fail) the runs waiting on `run`. Call after committing its final status."""
    waiting = db.scalars(
        select(CvRun).where(CvRun.video_id == run.video_id, CvRun.status == CvRunStatus.waiting)
    ).all()
    for dep in waiting:
        if str(run.id) not in (dep.inputs or {}).values():
            continue
        locked = db.get(CvRun, dep.id, with_for_update=True, populate_existing=True)
        if locked is None or locked.status != CvRunStatus.waiting:  # another input's finish handled it
            db.commit()
            continue
        state = _inputs_ready(db, locked)
        if state == "failed":
            fail(db, locked, f"input {run.kind} run {run.id} did not succeed")
            db.commit()
            input_finished(db, locked)
        elif state == "ready":
            _enqueue(db, locked, locked.created_by)
        else:
            db.commit()
