"""
`cv.movement` job: a hand-tracking run (and an object-detection run, if there is one) → hand–object contact
→ the configured movement classifier → movement events.

Each event becomes a `movement_events` row (the spec's event record) plus an AI annotation in the movement
category, so it lands on the Phase 2 timeline with the rest; hand–object contact episodes land on the
object-interaction track. An event's evidence frames are checked against the hand-tracking run's Parquet
rows before it is stored: every frame it names is a frame that track has keypoints for.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
from sqlalchemy import select

from egolabs import review
from egolabs.config import get_settings
from egolabs.cv import frames as frames_mod
from egolabs.cv import registry, runs, store
from egolabs.cv.adapters.base import VideoContext
from egolabs.cv.features import FINGER_NAMES
from egolabs.cv.movement import evidence
from egolabs.cv.movement.base import (
    Contact,
    HandState,
    MotionFrame,
    MovementClassifier,
    MovementDetection,
    ObjectState,
)
from egolabs.cv.movement.contact import find_contacts
from egolabs.events import record_event
from egolabs.models import (
    Annotation,
    AnnotationCategory,
    AnnotationSource,
    AnnotationType,
    CvRun,
    CvRunKind,
    CvRunStatus,
    LineageEdge,
    MovementClass,
    MovementEvent,
    MovementEventStatus,
    ObjectTrack,
    Video,
)
from egolabs.worker.runtime import JobContext, job_handler

BATCH = 60
CONTACT_GAP_S = 0.3  # contact may drop out this long within one interaction segment
CONTACT_MIN_FRAMES = 2
# Object tracks detected in fewer frames than this are left out of contact (one-off false detections).
MIN_OBJECT_TRACK_FRAMES = 5

HAND_COLUMNS = ["frame", "timestamp_s", "track_id", "handedness", "confidence", "kp_x", "kp_y", "kp_z",
                "wrist_vx_px_s", "wrist_vy_px_s"]  # fmt: skip


@dataclass
class _Interaction:
    handedness: str
    label: str
    frames: list[int] = field(default_factory=list)
    last_t: float = 0.0
    fingers: set[str] = field(default_factory=set)
    score: float = 0.0


class _Interactions:
    """Contact per (hand track, object track), merged into segments for the object-interaction track."""

    def __init__(self) -> None:
        self.open: dict[tuple[int, int], _Interaction] = {}
        self.done: list[tuple[int, int, _Interaction]] = []

    def frame(
        self, t: float, frame: int, contacts: list[Contact], hands: dict[int, str], labels: dict[int, str]
    ) -> None:
        now = set()
        for ct in contacts:
            key = (ct.hand_track_id, ct.object_track_id)
            now.add(key)
            seg = self.open.get(key)
            if seg is None or t - seg.last_t > CONTACT_GAP_S:
                self._close(key)
                seg = self.open[key] = _Interaction(hands[ct.hand_track_id], labels[ct.object_track_id])
            seg.frames.append(frame)
            seg.last_t = t
            seg.fingers.update(ct.fingers)
            seg.score += ct.score
        for key in [k for k, s in self.open.items() if k not in now and t - s.last_t > CONTACT_GAP_S]:
            self._close(key)

    def _close(self, key: tuple[int, int]) -> None:
        seg = self.open.pop(key, None)
        if seg is not None and len(seg.frames) >= CONTACT_MIN_FRAMES:
            self.done.append((*key, seg))

    def finish(self) -> list[tuple[int, int, _Interaction]]:
        for key in list(self.open):
            self._close(key)
        return self.done


def _by_frame(rows: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    out: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        out[r["frame"]].append(r)
    return out


def _label(cls: MovementClass, det: MovementDetection) -> str:
    a = det.attributes
    detail = a.get("gesture") or a.get("direction") or None
    return f"{cls.label} · {str(detail).replace('_', ' ')}" if detail else cls.label


@job_handler("cv.movement")
def movement(ctx: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    run_id = uuid.UUID(payload["run_id"])
    with ctx.session() as db:
        run = db.get(CvRun, run_id)
        if run is None:
            raise LookupError(f"cv run {run_id} not found")
        video = db.get(Video, run.video_id)
        assert video is not None
        run.status, run.started_at, run.error = CvRunStatus.running, datetime.now(UTC), None
        db.commit()
        name, config = run.adapter, dict(run.config)
        hand_id = (run.inputs or {}).get(CvRunKind.hand_tracking.value)
        obj_id = (run.inputs or {}).get(CvRunKind.object_detection.value)
        hand_run = db.get(CvRun, uuid.UUID(hand_id)) if hand_id else None
        obj_run = db.get(CvRun, uuid.UUID(obj_id)) if obj_id else None
        vinfo = VideoContext(
            str(video.id), video.sha256, video.width, video.height, video.fps, video.frame_count
        )
        width, height = video.width or 0, video.height or 0
        session_id = video.session_id
        timestamps = frames_mod.video_timestamps(video)
        hand_out = dict(hand_run.output) if hand_run else {}
        obj_out = dict(obj_run.output) if obj_run else {}
        hand_stride = hand_run.stride if hand_run else 1
        obj_stride = obj_run.stride if obj_run else 1
        real_objects = (
            set(db.scalars(select(ObjectTrack.track_id).where(ObjectTrack.run_id == obj_run.id,
                                                              ObjectTrack.frames_detected >= MIN_OBJECT_TRACK_FRAMES)))
            if obj_run else set()
        )  # fmt: skip
        total = (hand_run.frames_total if hand_run else None) or video.frame_count or 0

    classifier: MovementClassifier | None = None
    detections: list[MovementDetection] = []
    interactions = _Interactions()
    track_frames: dict[int, set[int]] = defaultdict(set)
    handedness: dict[int, str] = {}
    object_labels: dict[int, str] = {}
    try:
        if hand_run is None or hand_run.status != CvRunStatus.succeeded:
            raise ValueError("movement classification needs a successful hand-tracking run")
        if obj_run is not None and obj_run.status != CvRunStatus.succeeded:
            raise ValueError(f"object-detection run {obj_run.id} did not succeed")
        if not (width and height):
            raise ValueError("video has no known resolution")
        classifier = registry.create(name, config, "movement")
        with ctx.session() as db:
            mv = runs.model_version_for(db, classifier, name, config, "movement")
            mv_id, mv_label = mv.id, f"{mv.name} {mv.version}"
            row = db.get(CvRun, run_id)
            assert row is not None
            row.model_version_id, row.stride = mv_id, hand_stride
            db.commit()
        ctx.info(
            "Loaded classifier", adapter=name, model_version=mv_label, hand_run=hand_id, object_run=obj_id
        )
        classifier.reset(vinfo)

        processed = 0
        for lo in range(0, max(total, 1), store.CHUNK_FRAMES):
            hi = min(total - 1, lo + store.CHUNK_FRAMES - 1)
            if hi < lo:
                break
            hands = _by_frame(store.read_window(hand_out, "hands", lo, hi, HAND_COLUMNS).to_pylist())
            tips: dict[tuple[int, int], dict[str, float]] = defaultdict(dict)
            for f in store.read_window(
                hand_out, "fingers", lo, hi, ["frame", "track_id", "finger", "tip_speed_px_s"]
            ).to_pylist():
                tips[(f["frame"], f["track_id"])][f["finger"]] = f["tip_speed_px_s"]
            objects = (
                _by_frame(store.read_window(obj_out, "objects", max(0, lo - obj_stride + 1), hi).to_pylist())
                if obj_run else {}
            )  # fmt: skip
            batch: list[MotionFrame] = []
            first = lo + (-lo) % hand_stride
            for f in range(first, hi + 1, hand_stride):
                rows = hands.get(f, [])
                t = (
                    rows[0]["timestamp_s"]
                    if rows
                    else (timestamps[f] if f < len(timestamps) else f / (video.fps or 30.0))
                )
                states = []
                for h in rows:
                    tid = h["track_id"]
                    track_frames[tid].add(f)
                    handedness.setdefault(tid, h["handedness"])
                    states.append(HandState(tid, h["handedness"], h["confidence"],
                                            np.stack([h["kp_x"], h["kp_y"], h["kp_z"]], axis=1),
                                            (h["wrist_vx_px_s"], h["wrist_vy_px_s"]), tips.get((f, tid), {})))  # fmt: skip
                # Objects: this frame's detections, or the object run's latest frame before it (its stride).
                obj_rows: list[dict[str, Any]] = []
                for back in range(obj_stride):
                    if f - back in objects:
                        obj_rows = objects[f - back]
                        break
                objs = [ObjectState(o["track_id"], o["label"], o["score"], (o["bbox_x"], o["bbox_y"], o["bbox_w"], o["bbox_h"]))
                        for o in obj_rows if o["track_id"] in real_objects]  # fmt: skip
                for o in objs:
                    object_labels.setdefault(o.track_id, o.label)
                contacts = find_contacts(states, objs, width, height)
                interactions.frame(t, f, contacts, handedness, object_labels)
                batch.append(MotionFrame(f, t, states, objs, contacts))
                processed += 1
                if len(batch) >= BATCH:
                    detections += classifier.predict(batch)
                    batch = []
            if batch:
                detections += classifier.predict(batch)
            ctx.info("Classified", frames=processed, events=len(detections))
        detections += classifier.finish()
    except Exception as exc:
        with ctx.session() as db:
            r = db.get(CvRun, run_id)
            if r is not None:
                runs.fail(db, r, str(exc))
                db.commit()
                runs.input_finished(db, r)
        raise
    finally:
        if classifier is not None:
            classifier.close()

    review_below = settings.movement_review_confidence
    stats: dict[str, Any] = {"classes": {}, "skipped_inactive": {}, "dropped_frames": 0, "dropped_events": 0,
                             "needs_review": 0, "review_confidence": review_below}  # fmt: skip
    hand_parts = hand_out.get("hands", [])
    with ctx.session() as db:
        run = db.get(CvRun, run_id)
        assert run is not None
        classes = {c.name: c for c in db.scalars(select(MovementClass))}
        for det in sorted(detections, key=lambda d: (d.start_frame if d.frames else 0, d.name)):
            frames = [f for f in det.frames if f in track_frames.get(det.hand_track_id, ())]
            if len(frames) != len(det.frames):
                stats["dropped_frames"] += len(det.frames) - len(frames)
                keep = [i for i, f in enumerate(det.frames) if f in track_frames.get(det.hand_track_id, ())]
                det.measurements = {
                    k: [v[i] for i in keep] for k, v in det.measurements.items() if len(v) == len(det.frames)
                }
                det.frames = frames
            if not det.frames:
                stats["dropped_events"] += (
                    1  # names no keypoint frames of its track: not traceable, not stored
                )
                continue
            cls = classes.get(det.name)
            if cls is None:  # a model's own class: added as a custom class
                cls = MovementClass(name=det.name[:64], label=det.name.replace("_", " ").capitalize()[:120],
                                    description=f"Added by model {mv_label}", builtin=False)  # fmt: skip
                db.add(cls)
                db.flush()
                classes[det.name] = cls
            if not cls.active:
                stats["skipped_inactive"][det.name] = stats["skipped_inactive"].get(det.name, 0) + 1
                continue
            flagged = det.confidence < review_below
            stats["needs_review"] += flagged
            stats["classes"][det.name] = stats["classes"].get(det.name, 0) + 1
            start, end = det.frames[0], det.frames[-1]
            ts = lambda f: timestamps[f] if f < len(timestamps) else f / (video.fps or 30.0)  # noqa: E731
            chunks = {store.chunk_of(f) for f in det.frames}
            parts = [k for k in hand_parts if int(k.rsplit("part-", 1)[1].split(".")[0]) in chunks]
            event_id = uuid.uuid4()
            ann = Annotation(
                id=uuid.uuid4(), video_id=run.video_id, type=AnnotationType.segment, label=_label(cls, det)[:200],
                category=AnnotationCategory.movement, frame_start=start, frame_end=end,
                data={"event_id": str(event_id), "class": cls.name, "handedness": det.handedness,
                      "hand_track_id": det.hand_track_id, "fingers": list(det.fingers),
                      "object_track_id": det.object_track_id, "object_label": det.object_label,
                      "attributes": det.attributes, "run_id": str(run_id)},
                source=AnnotationSource.auto, confidence=det.confidence, model_version_id=mv_id,
                needs_review=flagged, cv_run_id=run_id,
            )  # fmt: skip
            db.add(ann)
            db.flush()
            db.add(MovementEvent(
                id=event_id, annotation_id=ann.id, video_id=run.video_id, session_id=session_id, run_id=run_id,
                hand_run_id=hand_run.id, object_run_id=obj_run.id if obj_run else None, model_version_id=mv_id,
                class_id=cls.id, start_frame=start, end_frame=end, start_s=ts(start), end_s=ts(end),
                handedness=det.handedness, hand_track_id=det.hand_track_id, fingers=list(det.fingers),
                object_track_id=det.object_track_id, object_label=det.object_label, confidence=det.confidence,
                status=MovementEventStatus.needs_review if flagged else MovementEventStatus.auto_detected,
                evidence={"frames": evidence.encode(det.frames), "frame_count": len(det.frames),
                          "measurements": det.measurements, "thresholds": det.thresholds, "rule": det.rule,
                          "keypoints": {"run_id": str(hand_run.id), "track_id": det.hand_track_id, "parts": parts}},
                attributes=det.attributes,
            ))  # fmt: skip
        segments = interactions.finish()
        for hand_tid, obj_tid, seg in segments:
            db.add(Annotation(
                video_id=run.video_id, type=AnnotationType.segment, label=f"{seg.handedness} hand · {seg.label}"[:200],
                category=AnnotationCategory.object, frame_start=seg.frames[0], frame_end=seg.frames[-1],
                data={"run_id": str(run_id), "hand_run_id": str(hand_run.id),
                      "object_run_id": str(obj_run.id) if obj_run else None, "hand_track_id": hand_tid,
                      "handedness": seg.handedness, "object_track_id": obj_tid, "object_label": seg.label,
                      "fingers": [f for f in FINGER_NAMES if f in seg.fingers], "contact_frames": len(seg.frames)},
                source=AnnotationSource.auto, confidence=min(1.0, seg.score / len(seg.frames)), model_version_id=mv_id,
                cv_run_id=run_id,
            ))  # fmt: skip
        edges = [("cv_run", hand_run.id, "input_of"), ("model_version", mv_id, "model_of")]
        if obj_run is not None:
            edges.append(("cv_run", obj_run.id, "input_of"))
        for parent_type, parent_id, relation in edges:
            db.add(LineageEdge(parent_type=parent_type, parent_id=parent_id, child_type="cv_run", child_id=run_id,
                               relation=relation, job_id=ctx.job_id))  # fmt: skip
        stored = sum(stats["classes"].values())
        # Phase 5: disagreement with other model versions, then auto-accept rules on the new events.
        stats.update(review.after_classification(db, run))
        run.status, run.finished_at = CvRunStatus.succeeded, datetime.now(UTC)
        run.frames_total, run.frames_processed = total, processed
        run.detections, run.tracks = stored, len(track_frames)
        run.mean_confidence = (
            float(np.mean([d.confidence for d in detections if d.frames and classes[d.name].active]))
            if stored else None
        )  # fmt: skip
        run.stats = {**stats, "contact_segments": len(segments), "source_size": [width, height]}
        record_event(db, "cv.run_succeeded",
                     f"Movement classification finished: {video.original_filename} ({stored} events)",
                     entity_type="cv_run", entity_id=run_id, data={"video_id": str(run.video_id), "kind": run.kind})  # fmt: skip
        if stats["needs_review"]:
            record_event(db, "movement.review_required",
                         f"Human review required: {stats['needs_review']} low-confidence events in {video.original_filename}",
                         entity_type="cv_run", entity_id=run_id, data={"video_id": str(run.video_id)})  # fmt: skip
        db.commit()
        runs.input_finished(db, run)
    ctx.info("Movement classification finished", frames=processed, events=stored, classes=stats["classes"],
             contact_segments=len(segments), needs_review=stats["needs_review"])  # fmt: skip
    return {"frames": processed, "events": stored, "model_version": mv_label}
