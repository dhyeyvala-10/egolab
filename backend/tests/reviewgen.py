"""
Stored classification output for review tests: a ready video, a hand-tracking run, and movement runs whose
events are written as the `cv.movement` job writes them (event row + AI timeline segment), then passed
through the same post-classification step (model disagreement, auto-accept rules). Exact inputs, no models.
"""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from egolabs import review
from egolabs.cv import registry
from egolabs.models import (
    Annotation,
    AnnotationCategory,
    AnnotationSource,
    AnnotationType,
    CaptureSession,
    CvRun,
    CvRunKind,
    CvRunStatus,
    ModelVersion,
    MovementClass,
    MovementEvent,
    MovementEventStatus,
    Video,
    VideoStatus,
)

FPS = 30.0
_clock = [datetime(2026, 9, 1, tzinfo=UTC)]


def _tick() -> datetime:
    _clock[0] += timedelta(seconds=1)
    return _clock[0]


@dataclass
class Ev:
    cls: str
    start: int
    end: int
    conf: float
    hand: str = "right"
    obj: str | None = None
    fingers: tuple[str, ...] = ()


def session(db: Session, name: str = "SESSION_2026_09_24_001", **fields) -> CaptureSession:
    s = CaptureSession(name=name, **fields)
    db.add(s)
    db.commit()
    return s


def video(db: Session, name: str = "clip.mp4", session_id: uuid.UUID | None = None, frames: int = 600,
          status: VideoStatus = VideoStatus.ready, quality_flags: list[str] | None = None) -> Video:  # fmt: skip
    digest = hashlib.sha256(f"{name}{uuid.uuid4()}".encode()).hexdigest()
    v = Video(original_filename=name, storage_key=f"raw/{digest}", sha256=digest, size_bytes=1000, status=status,
              session_id=session_id, width=640, height=480, fps=FPS, frame_count=frames, duration_s=frames / FPS,
              quality_flags=quality_flags or [])  # fmt: skip
    db.add(v)
    db.commit()
    return v


def model_version(
    db: Session, kind: str = "movement", config: dict | None = None, name: str = "rules"
) -> ModelVersion:
    config = config or {}
    version = f"1 cfg:{registry.config_hash(name, config, kind)}"
    mv = db.scalar(
        select(ModelVersion).where(ModelVersion.name == f"test-{kind}", ModelVersion.version == version)
    )
    if mv is None:
        mv = ModelVersion(name=f"test-{kind}", version=version, kind=kind, adapter=registry.target(name, kind),
                          config=config)  # fmt: skip
        db.add(mv)
        db.commit()
    return mv


def hand_run(db: Session, v: Video) -> CvRun:
    mv = model_version(db, "hand_tracking", name="mediapipe-hands")
    r = CvRun(video_id=v.id, kind=CvRunKind.hand_tracking.value, adapter="mediapipe-hands", config={},
              model_version_id=mv.id, status=CvRunStatus.succeeded, finished_at=_tick(), frames_total=v.frame_count)  # fmt: skip
    db.add(r)
    db.commit()
    return r


def movement_run(db: Session, v: Video, events: list[Ev], mv: ModelVersion | None = None,
                 hand: CvRun | None = None) -> tuple[CvRun, list[MovementEvent]]:  # fmt: skip
    mv = mv or model_version(db)
    hand = (
        hand
        or db.scalar(select(CvRun).where(CvRun.video_id == v.id, CvRun.kind == "hand_tracking"))
        or hand_run(db, v)
    )
    run = CvRun(video_id=v.id, kind=CvRunKind.movement.value, adapter=registry.name_for(mv.adapter, "movement"),
                config=mv.config, model_version_id=mv.id, status=CvRunStatus.running, inputs={"hand_tracking": str(hand.id)})  # fmt: skip
    db.add(run)
    db.flush()
    classes = {c.name: c for c in db.scalars(select(MovementClass))}
    out = []
    for e in events:
        cls = classes[e.cls]
        flagged = e.conf < 0.6
        eid = uuid.uuid4()
        ann = Annotation(video_id=v.id, type=AnnotationType.segment, label=cls.label + (f" · {e.obj}" if e.obj else ""),
                         category=AnnotationCategory.movement, frame_start=e.start, frame_end=e.end,
                         data={"event_id": str(eid), "class": cls.name, "handedness": e.hand, "hand_track_id": 1,
                               "fingers": list(e.fingers), "object_track_id": 1 if e.obj else None, "object_label": e.obj},
                         source=AnnotationSource.auto, confidence=e.conf, model_version_id=mv.id, needs_review=flagged,
                         cv_run_id=run.id)  # fmt: skip
        db.add(ann)
        db.flush()
        ev = MovementEvent(id=eid, annotation_id=ann.id, video_id=v.id, session_id=v.session_id, run_id=run.id,
                           hand_run_id=hand.id, model_version_id=mv.id, class_id=cls.id, start_frame=e.start,
                           end_frame=e.end, start_s=e.start / FPS, end_s=e.end / FPS, handedness=e.hand, hand_track_id=1,
                           fingers=list(e.fingers), object_track_id=1 if e.obj else None, object_label=e.obj,
                           confidence=e.conf,
                           status=MovementEventStatus.needs_review if flagged else MovementEventStatus.auto_detected,
                           evidence={"frames": [[e.start, e.end, 1]], "frame_count": e.end - e.start + 1,
                                     "measurements": {}, "thresholds": {}, "rule": "test"})  # fmt: skip
        db.add(ev)
        out.append(ev)
    db.flush()
    run.stats = review.after_classification(db, run)
    run.status, run.finished_at = CvRunStatus.succeeded, _tick()
    db.commit()
    return run, out
