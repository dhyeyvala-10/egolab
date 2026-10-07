"""
Running pipelines (spec Phase 7).

A run pins its videos and makes one step row per node and video (per-video steps) or per node (whole-run
steps). Each attempt at a step is its own job, so it has its own structured log (principle 7). When a step
ends, `advance` looks only at the steps after it: a per-video step whose inputs all succeeded is queued; if
an input was skipped (a corrupt video), it is skipped too; a whole-run step waits until every video's
steps before it have ended, and runs on the videos that made it through.

A failed step keeps the run from finishing, but nothing already done is lost: retrying makes a new
attempt of that step only, and the steps waiting on it carry on from there. Steps can also retry on their
own (the node's `retries`) after a transient failure: storage or the network being down, or a
worker dying mid-job (found by `recover_orphans` from the job heartbeat).

Every decision the engine makes is written to the run's own log (the run's `job_id`), so a run's logs are
complete: the engine's lines plus every attempt's job log.
"""

import logging
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from egolabs.config import get_settings
from egolabs.events import record_event
from egolabs.models import (
    CvRun,
    CvRunStatus,
    Job,
    JobLog,
    JobStatus,
    LogLevel,
    Pipeline,
    PipelineRun,
    PipelineRunStatus,
    PipelineStepAttempt,
    PipelineStepRun,
    PipelineVersion,
    RunTrigger,
    StepStatus,
    Video,
)
from egolabs.pipelines.graph import Graph
from egolabs.pipelines.steps import STEPS, MissingInput, SkipStep, StepEnv
from egolabs.worker.runtime import JobContext, job_handler

log = logging.getLogger("egolabs.pipelines")

ACTIVE = (StepStatus.queued, StepStatus.running, StepStatus.retry_wait)
DONE = (StepStatus.succeeded, StepStatus.failed, StepStatus.skipped, StepStatus.cancelled)
# Failures worth an automatic retry: the cause is outside the step and may clear on its own.
TRANSIENT = {"storage_unreachable", "worker_lost", "error"}
ERROR_LABELS = {
    "storage_unreachable": "Storage or network unreachable",
    "worker_lost": "Worker lost",
    "missing_input": "Missing input",
    "invalid_input": "Invalid input",
    "decode_error": "Video failed to decode",
    "model_error": "Model error",
    "error": "Error",
}


def step_job_type(step_type: str) -> str:
    return f"pipeline.{step_type}"


def classify(exc: BaseException) -> str:
    """A short failure reason for a step's exception."""
    from botocore.exceptions import BotoCoreError, ClientError, EndpointConnectionError

    from egolabs.cv.adapters.base import AdapterError
    from egolabs.cv.frames import FrameError
    from egolabs.ingest.media import MediaError

    if isinstance(exc, EndpointConnectionError | ConnectionError | TimeoutError):
        return "storage_unreachable"
    if isinstance(exc, ClientError):
        code = str(exc.response.get("Error", {}).get("Code", ""))
        return (
            "storage_unreachable"
            if code.startswith("5") or code in ("SlowDown", "ServiceUnavailable")
            else "error"
        )
    if isinstance(exc, BotoCoreError):
        return "storage_unreachable"
    if isinstance(exc, MissingInput):
        return "missing_input"
    if isinstance(exc, MediaError | FrameError):
        return "decode_error"
    if isinstance(exc, AdapterError):
        return "model_error"
    if isinstance(exc, ValueError):
        return "invalid_input"
    return "error"


# --- run log -------------------------------------------------------------------------------------------


def run_log(
    db: Session, run: PipelineRun, message: str, level: LogLevel = LogLevel.info, **data: Any
) -> None:
    """A line in the run's own log, in the caller's transaction."""
    if run.job_id is not None:
        db.add(JobLog(job_id=run.job_id, level=level, message=message, data=data))
    log.info(message, extra={"pipeline_run_id": str(run.id), "data": data})


def _label(db: Session, step: PipelineStepRun) -> str:
    name = STEPS[step.step_type].label if step.step_type in STEPS else step.step_type
    if step.video_id is None:
        return name
    video = db.get(Video, step.video_id)
    return f"{name} · {video.original_filename if video else step.video_id}"


# --- queueing ------------------------------------------------------------------------------------------


def _queue(db: Session, step: PipelineStepRun, reason: str, user_id: uuid.UUID | None) -> uuid.UUID:
    """Make the next attempt of `step` and its job (sent after commit by `send`)."""
    step.attempts += 1
    job = Job(type=step_job_type(step.step_type), created_by=user_id, payload={})
    db.add(job)
    db.flush()
    attempt = PipelineStepAttempt(step_run_id=step.id, number=step.attempts, job_id=job.id, reason=reason,
                                  created_by=user_id, status=StepStatus.queued)  # fmt: skip
    db.add(attempt)
    db.flush()
    job.payload = {"step_run_id": str(step.id), "attempt_id": str(attempt.id)}
    step.status, step.job_id, step.retry_at = StepStatus.queued, job.id, None
    step.error = step.error_kind = None
    step.finished_at = None
    return job.id


def send(db: Session, job_ids: list[uuid.UUID]) -> None:
    """Hand committed jobs to the worker queue (a job whose message is lost stays queued and is resent)."""
    if not job_ids:
        return
    from egolabs.worker.tasks import run_job_task

    for job_id in job_ids:
        result = run_job_task.delay(str(job_id))
        db.execute(update(Job).where(Job.id == job_id).values(celery_task_id=result.id))
    db.commit()


# --- advancing -----------------------------------------------------------------------------------------


@dataclass
class _Ctx:
    db: Session
    run: PipelineRun
    graph: Graph
    to_send: list[uuid.UUID]


def _load(db: Session, run_id: uuid.UUID) -> tuple[PipelineRun, Graph]:
    run = db.get(PipelineRun, run_id, with_for_update=True, populate_existing=True)
    if run is None:
        raise LookupError(f"pipeline run {run_id} not found")
    version = db.get(PipelineVersion, run.version_id)
    assert version is not None
    return run, Graph.load(version.graph)


def _step(db: Session, run_id: uuid.UUID, node_id: str, video_id: uuid.UUID | None) -> PipelineStepRun | None:
    q = select(PipelineStepRun).where(PipelineStepRun.run_id == run_id, PipelineStepRun.node_id == node_id)
    q = (
        q.where(PipelineStepRun.video_id == video_id)
        if video_id
        else q.where(PipelineStepRun.video_id.is_(None))
    )
    return db.scalar(q.with_for_update())


def _node_counts(db: Session, run_id: uuid.UUID, node_ids: list[str]) -> dict[str, dict[StepStatus, int]]:
    rows = db.execute(
        select(PipelineStepRun.node_id, PipelineStepRun.status, func.count())
        .where(PipelineStepRun.run_id == run_id, PipelineStepRun.node_id.in_(node_ids))
        .group_by(PipelineStepRun.node_id, PipelineStepRun.status)
    ).all()
    out: dict[str, dict[StepStatus, int]] = {n: {} for n in node_ids}
    for node, status, n in rows:
        out[node][StepStatus(status)] = n
    return out


def _skip(c: _Ctx, step: PipelineStepRun, reason: str) -> None:
    step.status, step.error, step.error_kind = StepStatus.skipped, reason, None
    step.finished_at = datetime.now(UTC)
    run_log(c.db, c.run, f"Skipped {_label(c.db, step)}: {reason}", node_id=step.node_id,
            step_run_id=str(step.id), video_id=str(step.video_id) if step.video_id else None)  # fmt: skip


def _decide(c: _Ctx, step: PipelineStepRun) -> bool:
    """Queue or skip a pending step if its inputs allow; True if it changed."""
    if step.status != StepStatus.pending:
        return False
    parents = c.graph.parents[step.node_id]
    if step.video_id is not None:  # per-video: the same video's steps before it
        states = []
        for p in parents:
            ps = _step(c.db, c.run.id, p, step.video_id)
            states.append(ps.status if ps else StepStatus.skipped)
        if any(s in (StepStatus.pending, *ACTIVE, StepStatus.failed) for s in states):
            return False
        skipped = [
            p for p, s in zip(parents, states, strict=True) if s in (StepStatus.skipped, StepStatus.cancelled)
        ]
        if skipped:
            _skip(c, step, f"{STEPS[c.graph.type_of(skipped[0])].label} was skipped for this video")
            return True
    else:  # whole-run: every video's steps before it
        counts = _node_counts(c.db, c.run.id, parents)
        for p in parents:
            if any(counts[p].get(s, 0) for s in (StepStatus.pending, *ACTIVE, StepStatus.failed)):
                return False
        if parents and all(counts[p].get(StepStatus.succeeded, 0) == 0 for p in parents):
            _skip(c, step, "no video made it through the steps before it")
            return True
    c.to_send.append(_queue(c.db, step, "first", c.run.created_by))
    return True


def _children(c: _Ctx, step: PipelineStepRun) -> list[PipelineStepRun]:
    out = []
    for child in c.graph.children[step.node_id]:
        s = _step(c.db, c.run.id, child, step.video_id if c.graph.per_video(child) else None)
        if s is not None:
            out.append(s)
    return out


def advance(db: Session, run: PipelineRun, graph: Graph, changed: list[PipelineStepRun]) -> list[uuid.UUID]:
    """Queue or skip what `changed` unblocks, then settle the run's status. The run row must be locked."""
    c = _Ctx(db, run, graph, [])
    if run.status == PipelineRunStatus.cancelled:
        return []
    work = deque(changed)
    while work:
        s = work.popleft()
        if s.status in (StepStatus.succeeded, StepStatus.skipped):
            for child in _children(c, s):
                if _decide(c, child) and child.status == StepStatus.skipped:
                    work.append(child)
    _settle(c)
    return c.to_send


def _settle(c: _Ctx) -> None:
    counts = dict(
        c.db.execute(
            select(PipelineStepRun.status, func.count())
            .where(PipelineStepRun.run_id == c.run.id)
            .group_by(PipelineStepRun.status)
        ).all()
    )
    n = {StepStatus(k): v for k, v in counts.items()}
    active = sum(n.get(s, 0) for s in ACTIVE)
    if active:
        if c.run.status != PipelineRunStatus.running:
            c.run.status, c.run.finished_at, c.run.error = PipelineRunStatus.running, None, None
        return
    failed = n.get(StepStatus.failed, 0)
    if failed:
        waiting = n.get(StepStatus.pending, 0)
        if c.run.status != PipelineRunStatus.failed:
            c.run.status, c.run.finished_at = PipelineRunStatus.failed, datetime.now(UTC)
            c.run.error = f"{failed} step{'s' if failed != 1 else ''} failed; {waiting} waiting on them"
            run_log(c.db, c.run, f"Run stopped: {c.run.error}. Retry the failed steps to carry on.", LogLevel.error,
                    failed=failed, waiting=waiting)  # fmt: skip
            _finish_controller(c.db, c.run, JobStatus.failed)
            record_event(c.db, "pipeline.run_failed", f"Pipeline run failed: {_run_name(c.db, c.run)} ({c.run.error})",
                         entity_type="pipeline_run", entity_id=c.run.id)  # fmt: skip
        return
    if n.get(StepStatus.pending, 0):
        # Nothing active or failed, yet steps are pending: their inputs are all done, so look again.
        pending = c.db.scalars(
            select(PipelineStepRun).where(PipelineStepRun.run_id == c.run.id,
                                          PipelineStepRun.status == StepStatus.pending).with_for_update()
        ).all()  # fmt: skip
        changed = [s for s in pending if _decide(c, s)]
        if changed:
            for s in changed:
                if s.status == StepStatus.skipped:
                    for child in _children(c, s):
                        _decide(c, child)
            _settle(c)
        else:
            log.warning(
                "pipeline run has pending steps that can't start", extra={"pipeline_run_id": str(c.run.id)}
            )
        return
    if c.run.status == PipelineRunStatus.running or c.run.finished_at is None:
        c.run.status, c.run.finished_at, c.run.error = PipelineRunStatus.succeeded, datetime.now(UTC), None
        done = n.get(StepStatus.succeeded, 0)
        skipped = n.get(StepStatus.skipped, 0)
        run_log(c.db, c.run, f"Run finished: {done} steps succeeded" + (f", {skipped} skipped" if skipped else ""),
                succeeded=done, skipped=skipped)  # fmt: skip
        _finish_controller(c.db, c.run, JobStatus.succeeded)
        record_event(c.db, "pipeline.run_succeeded", f"Pipeline run finished: {_run_name(c.db, c.run)}",
                     entity_type="pipeline_run", entity_id=c.run.id)  # fmt: skip


def _run_name(db: Session, run: PipelineRun) -> str:
    p = db.get(Pipeline, run.pipeline_id)
    return f"{p.name if p else 'pipeline'} #{run.number}"


def _finish_controller(db: Session, run: PipelineRun, status: JobStatus) -> None:
    if run.job_id is None:
        return
    job = db.get(Job, run.job_id)
    if job is not None:
        job.status, job.finished_at = status, datetime.now(UTC)
        job.error = run.error if status == JobStatus.failed else None
        job.result = {"run_id": str(run.id), "status": run.status.value}


# --- starting ------------------------------------------------------------------------------------------


def start_run(db: Session, version: PipelineVersion, video_ids: list[uuid.UUID], selector: dict[str, Any], *,
              trigger: RunTrigger, user_id: uuid.UUID | None,
              schedule_id: uuid.UUID | None = None) -> tuple[PipelineRun, list[uuid.UUID]]:  # fmt: skip
    """Create the run and its steps, queue the first steps, and commit. Returns (run, jobs to send)."""
    pipeline = db.get(Pipeline, version.pipeline_id, with_for_update=True)
    assert pipeline is not None
    graph = Graph.load(version.graph)
    number = (
        db.scalar(select(func.max(PipelineRun.number)).where(PipelineRun.pipeline_id == pipeline.id)) or 0
    ) + 1
    now = datetime.now(UTC)
    controller = Job(type="pipeline.run", status=JobStatus.running, created_by=user_id, started_at=now,
                     payload={"pipeline_id": str(pipeline.id), "version": version.number})  # fmt: skip
    db.add(controller)
    db.flush()
    run = PipelineRun(pipeline_id=pipeline.id, number=number, version_id=version.id, status=PipelineRunStatus.running,
                      trigger=trigger, schedule_id=schedule_id,
                      inputs={"selector": selector, "video_ids": [str(v) for v in video_ids]},
                      video_count=len(video_ids), job_id=controller.id, created_by=user_id, started_at=now)  # fmt: skip
    db.add(run)
    db.flush()
    controller.payload = {**controller.payload, "run_id": str(run.id)}
    rows = []
    for node in graph.order:
        step = STEPS[graph.type_of(node)]
        retries = int(graph.nodes[node].get("retries") or 0)
        targets: list[uuid.UUID | None] = list(video_ids) if step.per_video else [None]
        for vid in targets:
            rows.append(PipelineStepRun(run_id=run.id, node_id=node, step_type=step.key, video_id=vid,
                                        status=StepStatus.pending, max_attempts=1 + retries))  # fmt: skip
    db.add_all(rows)
    db.flush()
    run_log(db, run, f"Run #{number} of {pipeline.name} v{version.number} started on {len(video_ids)} video"
            f"{'s' if len(video_ids) != 1 else ''} ({len(rows)} steps)", trigger=trigger.value,
            videos=len(video_ids), steps=len(rows), version=version.number)  # fmt: skip
    record_event(db, "pipeline.run_started", f"Pipeline run started: {pipeline.name} #{number} "
                 f"({len(video_ids)} videos)", entity_type="pipeline_run", entity_id=run.id, actor_id=user_id)  # fmt: skip
    c = _Ctx(db, run, graph, [])
    roots = set(graph.roots())
    for s in rows:
        if s.node_id in roots:
            c.to_send.append(_queue(db, s, "first", user_id))
    _settle(c)
    db.commit()
    return run, c.to_send


# --- executing a step ----------------------------------------------------------------------------------


def _upstream(
    db: Session, run: PipelineRun, graph: Graph, step: PipelineStepRun
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for a in graph.ancestors(step.node_id):
        video = step.video_id if graph.per_video(a) else None
        if not graph.per_video(a) or step.video_id is not None:
            s = _step(db, run.id, a, video)
            if s is not None and s.status == StepStatus.succeeded:
                out[graph.type_of(a)] = dict(s.result or {})
    return out


def _videos_through(db: Session, run: PipelineRun, graph: Graph, node_id: str) -> list[uuid.UUID]:
    """Videos whose per-video steps before `node_id` all succeeded (all run videos if there are none)."""
    per_video = [a for a in graph.ancestors(node_id) if graph.per_video(a)]
    videos = [uuid.UUID(v) for v in run.inputs.get("video_ids", [])]
    if not per_video:
        return videos
    ok: dict[uuid.UUID, int] = {}
    for vid, n in db.execute(
        select(PipelineStepRun.video_id, func.count())
        .where(
            PipelineStepRun.run_id == run.id,
            PipelineStepRun.node_id.in_(per_video),
            PipelineStepRun.status == StepStatus.succeeded,
        )  # fmt: skip
        .group_by(PipelineStepRun.video_id)
    ).all():
        ok[vid] = n
    return [v for v in videos if ok.get(v, 0) == len(per_video)]


def execute_step(ctx: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
    step_id, attempt_id = uuid.UUID(payload["step_run_id"]), uuid.UUID(payload["attempt_id"])
    with ctx.session() as db:
        step = db.get(PipelineStepRun, step_id, with_for_update=True)
        attempt = db.get(PipelineStepAttempt, attempt_id)
        if step is None or attempt is None:
            raise LookupError(f"pipeline step {step_id} not found")
        if step.status != StepStatus.queued or step.job_id != ctx.job_id:
            ctx.warning(
                "This attempt is no longer the step's current one; nothing to do", status=step.status.value
            )
            return {"stale": True}
        run = db.get(PipelineRun, step.run_id)
        assert run is not None
        if run.status == PipelineRunStatus.cancelled:
            step.status = attempt.status = StepStatus.cancelled
            db.commit()
            return {"cancelled": True}
        version = db.get(PipelineVersion, run.version_id)
        assert version is not None
        graph = Graph.load(version.graph)
        stype = STEPS[step.step_type]
        now = datetime.now(UTC)
        step.status, attempt.status, attempt.started_at = StepStatus.running, StepStatus.running, now
        step.started_at = step.started_at or now
        env = StepEnv(ctx=ctx, step_run_id=step.id, run_id=run.id, node_id=step.node_id, video_id=step.video_id,
                      config=stype.config.model_validate(graph.nodes[step.node_id].get("config") or {}),
                      upstream=_upstream(db, run, graph, step), user_id=run.created_by)  # fmt: skip
        if not stype.per_video:
            env.video_ids = _videos_through(db, run, graph, step.node_id)
        label = _label(db, step)
        run_log(db, run, f"Started {label} (attempt {attempt.number})", node_id=step.node_id,
                step_run_id=str(step.id), attempt=attempt.number, job_id=str(ctx.job_id))  # fmt: skip
        db.commit()
    ctx.info(f"Step started: {label}", node_id=step.node_id, step_type=stype.key, attempt=attempt.number,
             video_id=str(env.video_id) if env.video_id else None, videos=len(env.video_ids) or None)  # fmt: skip
    try:
        result = stype.run(env) or {}
    except SkipStep as exc:
        _finish(ctx, step_id, attempt_id, StepStatus.skipped, error=str(exc))
        ctx.info(f"Step skipped: {exc}")
        return {"skipped": str(exc)}
    except Exception as exc:
        kind = classify(exc)
        ctx.log(LogLevel.error, f"Step failed ({ERROR_LABELS.get(kind, kind)}): {exc}", error_kind=kind)
        _finish(
            ctx, step_id, attempt_id, StepStatus.failed, error=f"{type(exc).__name__}: {exc}", error_kind=kind
        )
        raise
    _finish(ctx, step_id, attempt_id, StepStatus.succeeded, result=result)
    ctx.info(
        f"Step succeeded: {label}",
        **{k: v for k, v in result.items() if isinstance(v, str | int | float | bool)},
    )
    return result


def _backoff(attempt: int) -> timedelta:
    base = get_settings().pipeline_retry_backoff_s
    return timedelta(seconds=min(base * 2 ** (attempt - 1), 3600))


def _finish(ctx: JobContext, step_id: uuid.UUID, attempt_id: uuid.UUID, status: StepStatus, *,
            result: dict[str, Any] | None = None, error: str | None = None, error_kind: str | None = None) -> None:  # fmt: skip
    with ctx.session() as db:
        to_send = finish_step(
            db, step_id, attempt_id, status, result=result, error=error, error_kind=error_kind
        )
        db.commit()
        send(db, to_send)


def finish_step(db: Session, step_id: uuid.UUID, attempt_id: uuid.UUID | None, status: StepStatus, *,
                result: dict[str, Any] | None = None, error: str | None = None,
                error_kind: str | None = None) -> list[uuid.UUID]:  # fmt: skip
    """Record how an attempt ended and advance the run (caller commits, then sends the returned jobs)."""
    run_id = db.scalar(select(PipelineStepRun.run_id).where(PipelineStepRun.id == step_id))
    run, graph = _load(db, run_id)  # lock the run first, then the step (same order everywhere)
    step = db.get(PipelineStepRun, step_id, with_for_update=True, populate_existing=True)
    assert step is not None
    attempt = db.get(PipelineStepAttempt, attempt_id) if attempt_id else None
    now = datetime.now(UTC)
    if attempt is not None:
        attempt.status, attempt.finished_at = status, now
        attempt.error, attempt.error_kind = error, error_kind
    if step.status not in (StepStatus.running, StepStatus.queued):
        return []  # cancelled meanwhile, or already recorded
    label = _label(db, step)
    step.finished_at = now
    if status == StepStatus.succeeded:
        step.status, step.result, step.error, step.error_kind = StepStatus.succeeded, result or {}, None, None
        run_log(db, run, f"Succeeded {label}", node_id=step.node_id, step_run_id=str(step.id),
                seconds=round((now - (step.started_at or now)).total_seconds(), 2))  # fmt: skip
    elif status == StepStatus.skipped:
        step.status, step.error = StepStatus.skipped, error
        run_log(db, run, f"Skipped {label}: {error}", node_id=step.node_id, step_run_id=str(step.id))
    else:
        step.error, step.error_kind = (error or "")[:4000], error_kind
        if (
            error_kind in TRANSIENT
            and step.attempts < step.max_attempts
            and run.status != PipelineRunStatus.cancelled
        ):
            step.status, step.retry_at = StepStatus.retry_wait, now + _backoff(step.attempts)
            run_log(db, run, f"Failed {label} ({ERROR_LABELS.get(error_kind or '', error_kind)}); retrying at "
                    f"{step.retry_at:%H:%M:%S} UTC (attempt {step.attempts + 1} of {step.max_attempts})",
                    LogLevel.warning, node_id=step.node_id, step_run_id=str(step.id), error=error)  # fmt: skip
        else:
            step.status = StepStatus.failed
            run_log(db, run, f"Failed {label} ({ERROR_LABELS.get(error_kind or '', error_kind)}): {error}", LogLevel.error,
                    node_id=step.node_id, step_run_id=str(step.id), error_kind=error_kind)  # fmt: skip
    if run.status == PipelineRunStatus.cancelled:
        return []
    return advance(db, run, graph, [step])


for _key in STEPS:
    job_handler(step_job_type(_key))(execute_step)


# --- retry and cancel ----------------------------------------------------------------------------------


class StepStateError(ValueError):
    pass


def retry_steps(db: Session, run_id: uuid.UUID, step_ids: list[uuid.UUID] | None,
                user_id: uuid.UUID | None) -> tuple[list[PipelineStepRun], list[uuid.UUID]]:  # fmt: skip
    """New attempts of failed (or retry-waiting) steps: the given ones, or all of the run's. Finished steps
    are never touched. Caller commits, then sends."""
    run, graph = _load(db, run_id)
    if run.status == PipelineRunStatus.cancelled:
        raise StepStateError("The run was cancelled; start a new run instead")
    q = select(PipelineStepRun).where(PipelineStepRun.run_id == run.id)
    q = (
        q.where(PipelineStepRun.id.in_(step_ids))
        if step_ids
        else q.where(PipelineStepRun.status.in_((StepStatus.failed, StepStatus.retry_wait)))
    )
    steps = list(db.scalars(q.with_for_update()).all())
    if step_ids and len(steps) != len(set(step_ids)):
        raise LookupError("Step not found in this run")
    bad = [s for s in steps if s.status not in (StepStatus.failed, StepStatus.retry_wait)]
    if bad:
        raise StepStateError(
            f"Only failed steps can be retried; {_label(db, bad[0])} is {bad[0].status.value}"
        )
    if not steps:
        raise StepStateError("Nothing to retry: no step of this run has failed")
    to_send = []
    for s in steps:
        run_log(db, run, f"Retry of {_label(db, s)} requested (attempt {s.attempts + 1})", node_id=s.node_id,
                step_run_id=str(s.id), user_id=str(user_id) if user_id else None)  # fmt: skip
        to_send.append(_queue(db, s, "manual_retry", user_id))
    if run.status != PipelineRunStatus.running:
        run.status, run.finished_at, run.error = PipelineRunStatus.running, None, None
        if run.job_id:
            job = db.get(Job, run.job_id)
            if job is not None:
                job.status, job.finished_at, job.error = JobStatus.running, None, None
    return steps, to_send


def cancel_run(db: Session, run_id: uuid.UUID, user_id: uuid.UUID | None) -> PipelineRun:
    """Stop a run: steps not yet started are cancelled; running steps finish, but nothing starts after them."""
    run, _ = _load(db, run_id)
    if run.status in (PipelineRunStatus.succeeded, PipelineRunStatus.cancelled):
        raise StepStateError(f"The run is already {run.status.value}")
    steps = db.scalars(select(PipelineStepRun).where(
        PipelineStepRun.run_id == run.id,
        PipelineStepRun.status.in_((StepStatus.pending, StepStatus.queued, StepStatus.retry_wait))).with_for_update()).all()  # fmt: skip
    for s in steps:
        if s.status == StepStatus.queued and s.job_id:
            db.execute(update(Job).where(Job.id == s.job_id, Job.status == JobStatus.queued)
                       .values(status=JobStatus.cancelled, finished_at=func.now()))  # fmt: skip
            db.execute(update(PipelineStepAttempt).where(PipelineStepAttempt.job_id == s.job_id)
                       .values(status=StepStatus.cancelled, finished_at=func.now()))  # fmt: skip
        s.status, s.finished_at = StepStatus.cancelled, datetime.now(UTC)
    run.status, run.finished_at = PipelineRunStatus.cancelled, datetime.now(UTC)
    run.error = "Cancelled"
    run_log(db, run, f"Run cancelled; {len(steps)} steps that hadn't started won't run", LogLevel.warning,
            user_id=str(user_id) if user_id else None)  # fmt: skip
    _finish_controller(db, run, JobStatus.cancelled)
    return run


# --- the scheduler tick --------------------------------------------------------------------------------


def due_retries(db: Session, now: datetime) -> list[uuid.UUID]:
    """Queue the automatic retries whose time has come. Caller commits, then sends."""
    to_send: list[uuid.UUID] = []
    ids = db.scalars(select(PipelineStepRun.id).where(PipelineStepRun.status == StepStatus.retry_wait,
                                                     PipelineStepRun.retry_at <= now).limit(500)).all()  # fmt: skip
    for sid in ids:
        run_id = db.scalar(select(PipelineStepRun.run_id).where(PipelineStepRun.id == sid))
        run, _ = _load(db, run_id)
        s = db.get(PipelineStepRun, sid, with_for_update=True, populate_existing=True)
        if s is None or s.status != StepStatus.retry_wait:
            continue
        run_log(db, run, f"Retrying {_label(db, s)} automatically (attempt {s.attempts + 1} of {s.max_attempts})",
                node_id=s.node_id, step_run_id=str(s.id))  # fmt: skip
        to_send.append(_queue(db, s, "auto_retry", run.created_by))
    return to_send


def recover_orphans(db: Session, now: datetime) -> tuple[int, list[uuid.UUID]]:
    """Jobs left `running` by a worker that died (no heartbeat): fail them, and their pipeline step (which
    may retry) and model run. Returns (jobs recovered, jobs to send); caller commits, then sends."""
    stale_before = now - timedelta(seconds=get_settings().job_stale_after_s)
    jobs = db.scalars(
        select(Job).where(Job.status == JobStatus.running, Job.type != "pipeline.run",
                          func.coalesce(Job.heartbeat_at, Job.started_at) < stale_before)
        .with_for_update(skip_locked=True).limit(200)
    ).all()  # fmt: skip
    to_send: list[uuid.UUID] = []
    for job in jobs:
        seen = job.heartbeat_at or job.started_at
        message = f"Worker lost: no heartbeat since {seen:%Y-%m-%d %H:%M:%S} UTC" if seen else "Worker lost"
        job.status, job.error, job.finished_at = JobStatus.failed, message, now
        db.add(
            JobLog(job_id=job.id, level=LogLevel.error, message=message, data={"recovered_by": "scheduler"})
        )
        for run in db.scalars(
            select(CvRun).where(CvRun.job_id == job.id, CvRun.status == CvRunStatus.running)
        ):
            run.status, run.error, run.finished_at = CvRunStatus.failed, message, now
        attempt = db.scalar(select(PipelineStepAttempt).where(PipelineStepAttempt.job_id == job.id))
        if attempt is not None:
            to_send += finish_step(db, attempt.step_run_id, attempt.id, StepStatus.failed, error=message,
                                   error_kind="worker_lost")  # fmt: skip
        log.warning("recovered orphaned job", extra={"job_id": str(job.id), "type": job.type})
    return len(jobs), to_send


def tick(db: Session, now: datetime | None = None) -> dict[str, int]:
    """Run once a minute (Celery beat): fire due schedules, queue due retries, recover orphaned jobs."""
    from egolabs.pipelines import schedules

    now = now or datetime.now(UTC)
    fired = schedules.fire_due(db, now)
    retried = due_retries(db, now)
    db.commit()
    send(db, retried)
    orphaned, resend = recover_orphans(db, now)
    db.commit()
    send(db, resend)
    return {"schedules_fired": fired, "retries": len(retried), "orphans": orphaned}
