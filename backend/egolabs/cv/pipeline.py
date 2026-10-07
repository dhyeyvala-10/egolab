"""
`cv.hand_tracking` job: raw video → frames → configured adapter → tracking → smoothing → features →
Parquet (per frame) + Postgres summaries (run, tracks) + timeline annotations (track and finger-activity
segments). Every output references the model version that produced it.
"""

import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from egolabs import quality
from egolabs.config import get_settings
from egolabs.cv import frames as frames_mod
from egolabs.cv import registry, runs
from egolabs.cv.adapters.base import HandTrackingAdapter, VideoContext
from egolabs.cv.features import FINGER_NAMES, FingerRow, HandRow, TrackFeatures
from egolabs.cv.frames import iter_frames
from egolabs.cv.store import ChunkWriter
from egolabs.cv.tracking import HandTracker
from egolabs.events import record_event
from egolabs.models import (
    Annotation,
    AnnotationCategory,
    AnnotationSource,
    AnnotationType,
    CvRun,
    CvRunStatus,
    HandTrack,
    LineageEdge,
    Video,
)
from egolabs.worker.runtime import JobContext, job_handler

BATCH = 32
PROGRESS_EVERY = 600  # frames between progress updates

# Finger activity: a fingertip moving faster than this (fraction of the frame width per second) for at
# least ACTIVE_MIN_FRAMES processed frames becomes a segment on the timeline's finger track.
ACTIVE_SPEED_FRACTION = 0.25
ACTIVE_MIN_FRAMES = 5
ACTIVE_GAP_FRAMES = 3


@dataclass
class _TrackStats:
    handedness: dict[str, int] = field(default_factory=dict)
    first: int = 0
    last: int = 0
    frames: int = 0
    confidence: float = 0.0
    speed_sum: float = 0.0
    speed_peak: float = 0.0
    path: float = 0.0


@dataclass
class _Activity:
    """Open run of fast fingertip frames for one track + finger."""

    start: int
    last: int
    frames: int = 0
    peak: float = 0.0
    confidence: float = 0.0


@dataclass
class _FingerStats:
    n: int = 0
    visibility: float = 0.0
    occluded: int = 0
    speed_sum: float = 0.0
    speed_peak: float = 0.0
    speeds: list[float] = field(default_factory=list)


class _Aggregator:
    def __init__(self, width: int, stride: int) -> None:
        self.stride = stride
        self.tracks: dict[int, _TrackStats] = {}
        self.fingers = {name: _FingerStats() for name in FINGER_NAMES}
        self.threshold = ACTIVE_SPEED_FRACTION * width
        self.open: dict[tuple[int, str], _Activity] = {}
        self.handed: dict[tuple[int, str], str] = {}
        self.segments: list[tuple[int, str, str, _Activity]] = []  # (track, handedness, finger, activity)
        self.frames_with_hands = 0
        self.detections = 0
        self.conf_sum = 0.0
        self.no_hand_runs: list[
            list[int]
        ] = []  # [first, last] frames of runs of processed frames with no hand
        self._prev: tuple[int, bool] | None = None  # (index, had hands) of the previous processed frame

    def frame(self, index: int, hands: list[HandRow], fingers: list[FingerRow]) -> None:
        if hands:
            self.frames_with_hands += 1
        elif self._prev is not None and not self._prev[1] and self.no_hand_runs:
            self.no_hand_runs[-1][1] = index
        else:
            self.no_hand_runs.append([index, index])
        self._prev = (index, bool(hands))
        for h in hands:
            self.detections += 1
            self.conf_sum += h.confidence
            t = self.tracks.setdefault(h.track_id, _TrackStats(first=index))
            t.handedness[h.handedness] = t.handedness.get(h.handedness, 0) + 1
            t.last, t.frames = index, t.frames + 1
            t.confidence += h.confidence
            t.speed_sum += h.wrist_speed
            t.speed_peak = max(t.speed_peak, h.wrist_speed)
            t.path = h.path_length_px
        gap = (ACTIVE_GAP_FRAMES + 1) * self.stride
        for f in fingers:
            s = self.fingers[f.finger]
            s.n += 1
            s.visibility += f.visibility
            s.occluded += int(f.occluded)
            s.speed_sum += f.tip_speed
            s.speed_peak = max(s.speed_peak, f.tip_speed)
            if len(s.speeds) < 200_000:
                s.speeds.append(f.tip_speed)
            key = (f.track_id, f.finger)
            act = self.open.get(key)
            if f.tip_speed >= self.threshold:
                if act is None or index - act.last > gap:
                    self._close(key)
                    act = self.open[key] = _Activity(index, index)
                else:
                    act.last = index
                act.frames += 1
                act.peak = max(act.peak, f.tip_speed)
                act.confidence += f.confidence
                self.handed[key] = f.handedness
            elif act is not None and index - act.last > gap:
                self._close(key)

    def _close(self, key: tuple[int, str]) -> None:
        act = self.open.pop(key, None)
        if act is not None and act.frames >= ACTIVE_MIN_FRAMES:
            self.segments.append((key[0], self.handed[key], key[1], act))

    def finish(self) -> None:
        for key in list(self.open):
            self._close(key)


@job_handler("cv.hand_tracking")
def hand_tracking(ctx: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
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
        name, config, stride = run.adapter, dict(run.config), run.stride
        vinfo = VideoContext(
            str(video.id), video.sha256, video.width, video.height, video.fps, video.frame_count
        )
        key, kind, fps = video.storage_key, video.source_kind, video.fps
        width, height = video.width or 0, video.height or 0
        timestamps = frames_mod.video_timestamps(video)
        exact_timing = bool((video.derivatives or {}).get("frame_index"))

    adapter: HandTrackingAdapter | None = None
    try:
        adapter = registry.create(name, config)
        with ctx.session() as db:
            mv = runs.model_version_for(db, adapter, name, config)
            mv_id, mv_label = mv.id, f"{mv.name} {mv.version}"
            row = db.get(CvRun, run_id)
            assert row is not None
            row.model_version_id = mv_id
            db.commit()
        ctx.info("Loaded adapter", adapter=name, model_version=mv_label, stride=stride)
        adapter.reset(vinfo)

        with tempfile.TemporaryDirectory(dir=settings.work_dir, prefix="egolabs-cv-") as tmp:
            source, pattern = frames_mod.download_source(key, kind, Path(tmp))
            if not (width and height):
                raise ValueError("video has no known resolution")

            tracker = HandTracker()
            features: dict[int, TrackFeatures] = {}
            writer = ChunkWriter(str(vinfo.video_id), str(run_id), str(mv_id))
            agg = _Aggregator(width, stride)
            processed = 0
            batch = []

            def flush_batch() -> None:
                nonlocal processed
                for result in adapter.predict(batch):  # type: ignore[union-attr]
                    hand_rows: list[HandRow] = []
                    finger_rows: list[FingerRow] = []
                    for tracked in tracker.update(result):
                        feats = features.setdefault(
                            tracked.track_id, TrackFeatures(tracked.track_id, width, height)
                        )
                        h, fs = feats.step(result.frame_index, result.timestamp_s, tracked.detection)
                        hand_rows.append(h)
                        finger_rows += fs
                    agg.frame(result.frame_index, hand_rows, finger_rows)
                    writer.add(result.frame_index, hand_rows, finger_rows)
                    processed += 1
                    if processed % PROGRESS_EVERY == 0:
                        ctx.info("Tracking", frames=processed, hands=agg.detections, tracks=len(agg.tracks))
                        with ctx.session() as db:
                            r = db.get(CvRun, run_id)
                            assert r is not None
                            r.frames_processed = processed
                            db.commit()
                batch.clear()

            for frame in iter_frames(source, width=width, height=height, timestamps=timestamps, stride=stride,
                                     sequence_pattern=pattern, sequence_fps=fps):  # fmt: skip
                batch.append(frame)
                if len(batch) >= BATCH:
                    flush_batch()
            if batch:
                flush_batch()

        summary = tracker.finish()
        agg.finish()
        output = writer.close()
        ctx.info("Stored keypoints", hands_rows=output["rows"]["hands"], finger_rows=output["rows"]["fingers"],
                 parts=len(output["hands"]))  # fmt: skip
    except Exception as exc:
        with ctx.session() as db:
            r = db.get(CvRun, run_id)
            if r is not None:
                runs.fail(db, r, str(exc))
                db.commit()
                runs.input_finished(db, r)
        raise
    finally:
        if adapter is not None:
            adapter.close()

    missing_total = sum(summary.missing.values())
    finger_stats = {}
    for fname, s in agg.fingers.items():
        speeds = np.asarray(s.speeds) if s.speeds else np.zeros(1)
        finger_stats[fname] = {
            "samples": s.n,
            "visibility": round(s.visibility / s.n, 4) if s.n else None,
            "occluded_rate": round(s.occluded / s.n, 4) if s.n else None,
            "mean_speed_px_s": round(s.speed_sum / s.n, 2) if s.n else None,
            "p95_speed_px_s": round(float(np.percentile(speeds, 95)), 2) if s.n else None,
            "peak_speed_px_s": round(s.speed_peak, 2) if s.n else None,
        }

    with ctx.session() as db:
        run = db.get(CvRun, run_id)
        assert run is not None
        video = db.get(Video, run.video_id)
        assert video is not None
        for tid, t in agg.tracks.items():
            handed = max(t.handedness, key=lambda k: t.handedness[k])
            conf = t.confidence / t.frames
            db.add(HandTrack(run_id=run_id, model_version_id=mv_id, track_id=tid, handedness=handed,
                             first_frame=t.first, last_frame=t.last, frames_detected=t.frames,
                             missing_detections=summary.missing.get(tid, 0), mean_confidence=conf,
                             path_length_px=t.path, mean_speed_px_s=t.speed_sum / t.frames,
                             peak_speed_px_s=t.speed_peak))  # fmt: skip
            # One segment per track on the timeline's hand-detection track.
            db.add(Annotation(video_id=video.id, type=AnnotationType.segment, label=f"{handed} hand",
                              category=AnnotationCategory.hand, frame_start=t.first, frame_end=t.last,
                              data={"run_id": str(run_id), "track_id": tid, "frames_detected": t.frames},
                              source=AnnotationSource.auto, confidence=min(1.0, conf), model_version_id=mv_id,
                              cv_run_id=run_id))  # fmt: skip
        for tid, handed, finger, act in agg.segments:
            db.add(Annotation(video_id=video.id, type=AnnotationType.segment, label=f"{finger} moving",
                              category=AnnotationCategory.finger, frame_start=act.start, frame_end=act.last,
                              data={"run_id": str(run_id), "track_id": tid, "finger": finger, "handedness": handed,
                                    "peak_speed_px_s": round(act.peak, 1)},
                              source=AnnotationSource.auto, confidence=min(1.0, act.confidence / act.frames),
                              model_version_id=mv_id, cv_run_id=run_id))  # fmt: skip
        for parent_type, parent_id, relation in (
            ("video", video.id, "input_of"),
            ("model_version", mv_id, "model_of"),
        ):
            db.add(LineageEdge(parent_type=parent_type, parent_id=parent_id, child_type="cv_run", child_id=run_id,
                               relation=relation, job_id=ctx.job_id))  # fmt: skip
        run.status, run.finished_at = CvRunStatus.succeeded, datetime.now(UTC)
        run.frames_total = video.frame_count
        run.frames_processed = processed
        run.frames_with_hands = agg.frames_with_hands
        run.detections = agg.detections
        run.tracks = len(agg.tracks)
        run.missing_detections = missing_total
        run.tracking_failures = len(summary.failures)
        run.mean_confidence = agg.conf_sum / agg.detections if agg.detections else None
        run.output = output
        run.stats = {
            "fingers": finger_stats,
            "failures": [vars(f) for f in summary.failures[:500]],
            "frames_without_hands": processed - agg.frames_with_hands,
            "no_hand_ranges": agg.no_hand_runs[:500],
            "finger_activity_segments": len(agg.segments),
            "exact_timing": exact_timing,
            "source_size": [width, height],
            "activity_speed_px_s": round(agg.threshold, 1),
        }
        db.flush()
        row = db.get(Video, run.video_id)
        if row is not None:
            quality.refresh(db, row)  # hand_tracking_failures follows the latest run
        record_event(db, "cv.run_succeeded",
                     f"Hand tracking finished: {video.original_filename} ({len(agg.tracks)} tracks)",
                     entity_type="cv_run", entity_id=run_id, data={"video_id": str(video.id)})  # fmt: skip
        db.commit()
        runs.input_finished(db, run)
    ctx.info("Hand tracking finished", frames=processed, frames_with_hands=agg.frames_with_hands,
             tracks=len(agg.tracks), missing_detections=missing_total, tracking_failures=len(summary.failures))  # fmt: skip
    return {
        "frames": processed,
        "tracks": len(agg.tracks),
        "detections": agg.detections,
        "model_version": mv_label,
    }
