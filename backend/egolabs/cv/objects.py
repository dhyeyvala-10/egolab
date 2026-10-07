"""
`cv.object_detection` job: raw video → frames → configured object detector → IoU tracking → Parquet (a box
per object per frame) + a summary row per object track. Every row references the model version.

Contact between hands and these objects is worked out by the movement run that reads both
(`egolabs.cv.movement.job`), so re-running either model re-derives the interactions.
"""

import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from egolabs.config import get_settings
from egolabs.cv import frames as frames_mod
from egolabs.cv import registry, runs
from egolabs.cv.adapters.base import ObjectDetectionAdapter, VideoContext
from egolabs.cv.object_tracking import ObjectTracker
from egolabs.cv.store import ObjectChunkWriter, ObjectRow
from egolabs.events import record_event
from egolabs.models import CvRun, CvRunStatus, LineageEdge, ObjectTrack, Video
from egolabs.worker.runtime import JobContext, job_handler

BATCH = 16
PROGRESS_EVERY = 600


@dataclass
class _Track:
    label: str
    first: int
    last: int = 0
    frames: int = 0
    score_sum: float = 0.0
    score_max: float = 0.0
    box_sum: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    path: float = 0.0
    center: tuple[float, float] | None = None


@job_handler("cv.object_detection")
def object_detection(ctx: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
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

    adapter: ObjectDetectionAdapter | None = None
    tracks: dict[int, _Track] = {}
    processed = frames_with_objects = detections = 0
    try:
        adapter = registry.create(name, config, "object_detection")
        with ctx.session() as db:
            mv = runs.model_version_for(db, adapter, name, config, "object_detection")
            mv_id, mv_label = mv.id, f"{mv.name} {mv.version}"
            row = db.get(CvRun, run_id)
            assert row is not None
            row.model_version_id = mv_id
            db.commit()
        ctx.info("Loaded adapter", adapter=name, model_version=mv_label, stride=stride)
        adapter.reset(vinfo)
        if not (width and height):
            raise ValueError("video has no known resolution")

        tracker = ObjectTracker()
        writer = ObjectChunkWriter(vinfo.video_id, str(run_id), str(mv_id))
        with tempfile.TemporaryDirectory(dir=settings.work_dir, prefix="egolabs-obj-") as tmp:
            source, pattern = frames_mod.download_source(key, kind, Path(tmp))
            batch = []

            def flush_batch() -> None:
                nonlocal processed, frames_with_objects, detections
                for result in adapter.predict(batch):  # type: ignore[union-attr]
                    rows = []
                    for tracked in tracker.update(result):
                        d = tracked.detection
                        rows.append(ObjectRow(result.frame_index, result.timestamp_s, tracked.track_id, d.label,
                                              d.score, d.bbox))  # fmt: skip
                        t = tracks.setdefault(tracked.track_id, _Track(d.label, result.frame_index))
                        t.last, t.frames = result.frame_index, t.frames + 1
                        t.score_sum, t.score_max = t.score_sum + d.score, max(t.score_max, d.score)
                        t.box_sum = [a + b for a, b in zip(t.box_sum, d.bbox, strict=True)]
                        c = ((d.bbox[0] + d.bbox[2] / 2) * width, (d.bbox[1] + d.bbox[3] / 2) * height)
                        if t.center is not None:
                            t.path += ((c[0] - t.center[0]) ** 2 + (c[1] - t.center[1]) ** 2) ** 0.5
                        t.center = c
                    writer.add(result.frame_index, rows)
                    processed += 1
                    detections += len(rows)
                    frames_with_objects += bool(rows)
                    if processed % PROGRESS_EVERY == 0:
                        ctx.info("Detecting", frames=processed, detections=detections, tracks=len(tracks))
                        with ctx.session() as db:
                            r = db.get(CvRun, run_id)
                            assert r is not None
                            r.frames_processed = processed
                            db.commit()
                batch.clear()

            for frame in frames_mod.iter_frames(source, width=width, height=height, timestamps=timestamps,
                                                stride=stride, sequence_pattern=pattern, sequence_fps=fps):  # fmt: skip
                batch.append(frame)
                if len(batch) >= BATCH:
                    flush_batch()
            if batch:
                flush_batch()
        summary = tracker.finish()
        output = writer.close()
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

    labels: dict[str, dict[str, Any]] = {}
    for t in tracks.values():
        lab = labels.setdefault(t.label, {"tracks": 0, "detections": 0, "score_sum": 0.0})
        lab["tracks"] += 1
        lab["detections"] += t.frames
        lab["score_sum"] += t.score_sum
    for lab in labels.values():
        lab["mean_score"] = round(lab.pop("score_sum") / lab["detections"], 4)

    with ctx.session() as db:
        run = db.get(CvRun, run_id)
        assert run is not None
        video = db.get(Video, run.video_id)
        assert video is not None
        for tid, t in tracks.items():
            db.add(ObjectTrack(run_id=run_id, model_version_id=mv_id, track_id=tid, label=t.label,
                               first_frame=t.first, last_frame=t.last, frames_detected=t.frames,
                               missing_detections=summary.missing.get(tid, 0), mean_score=t.score_sum / t.frames,
                               max_score=t.score_max, mean_bbox=[round(v / t.frames, 5) for v in t.box_sum],
                               path_length_px=t.path))  # fmt: skip
        for parent_type, parent_id, relation in (
            ("video", video.id, "input_of"),
            ("model_version", mv_id, "model_of"),
        ):
            db.add(LineageEdge(parent_type=parent_type, parent_id=parent_id, child_type="cv_run", child_id=run_id,
                               relation=relation, job_id=ctx.job_id))  # fmt: skip
        score_sum = sum(t.score_sum for t in tracks.values())
        run.status, run.finished_at = CvRunStatus.succeeded, datetime.now(UTC)
        run.frames_total, run.frames_processed = video.frame_count, processed
        run.detections, run.tracks = detections, len(tracks)
        run.missing_detections = sum(summary.missing.values())
        run.mean_confidence = score_sum / detections if detections else None
        run.output = output
        run.stats = {
            "labels": labels,
            "frames_with_objects": frames_with_objects,
            "source_size": [width, height],
        }
        record_event(db, "cv.run_succeeded",
                     f"Object detection finished: {video.original_filename} ({len(tracks)} objects)",
                     entity_type="cv_run", entity_id=run_id, data={"video_id": str(video.id), "kind": run.kind})  # fmt: skip
        db.commit()
        runs.input_finished(db, run)
    ctx.info("Object detection finished", frames=processed, detections=detections, tracks=len(tracks),
             labels=sorted(labels))  # fmt: skip
    return {"frames": processed, "tracks": len(tracks), "detections": detections, "model_version": mv_label}
