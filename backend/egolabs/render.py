"""
Annotated videos: the video with its hand skeletons, object boxes, and movement events drawn on, rendered
frame by frame (every source frame, numbered like the proxy) and encoded for download.

It reads a hand run's keypoints and an object run's boxes from Parquet one chunk at a time, and the
movement run's current events (corrections in place of the predictions they replaced, rejected ones left
out), so memory stays flat however long the video is. With a strided run, each processed frame's keypoints
stay on screen until the next processed frame.
"""

import subprocess
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from sqlalchemy import select

from egolabs import storage
from egolabs.config import get_settings
from egolabs.cv import frames as frames_mod
from egolabs.cv import store
from egolabs.cv.keypoints import CONNECTIONS
from egolabs.events import record_event
from egolabs.ingest.media import input_args
from egolabs.models import (
    AnnotatedVideo,
    BuildStatus,
    CvRun,
    LineageEdge,
    MovementClass,
    MovementEvent,
    MovementEventStatus,
    Video,
)
from egolabs.worker.runtime import JobContext, job_handler

# BGR colours: the app's AI purple for skeletons, its terracotta accent for objects.
SKELETON = (237, 58, 124)
OBJECT = (42, 83, 181)
WHITE = (255, 255, 255)
INK = (27, 36, 43)
FONT = cv2.FONT_HERSHEY_SIMPLEX


class _Chunks:
    """Rows of one Parquet kind by frame, loading a chunk only when playback reaches it."""

    def __init__(self, output: dict[str, Any], kind: str, columns: list[str]):
        self.output, self.kind, self.columns = output or {}, kind, columns
        self.size = int(self.output.get("chunk_frames", store.CHUNK_FRAMES))
        self.chunk = -1
        self.rows: dict[int, list[dict[str, Any]]] = {}

    def at(self, frame: int) -> list[dict[str, Any]]:
        c = frame // self.size
        if c != self.chunk:
            self.chunk = c
            t = store.read_window(
                self.output, self.kind, c * self.size, (c + 1) * self.size - 1, self.columns
            )
            self.rows = {}
            for r in t.to_pylist():
                self.rows.setdefault(r["frame"], []).append(r)
        return self.rows.get(frame, [])


def _label(frame: np.ndarray, text: str, org: tuple[int, int], scale: float, fg: tuple[int, int, int],
           bg: tuple[int, int, int], alpha: float = 0.78) -> int:  # fmt: skip
    """Text on a translucent pill; returns the pill's height."""
    thick = max(1, int(round(scale * 2)))
    (tw, th), base = cv2.getTextSize(text, FONT, scale, thick)
    pad = max(3, int(th * 0.45))
    x, y = org
    x2, y2 = min(frame.shape[1] - 1, x + tw + 2 * pad), min(frame.shape[0] - 1, y + th + base + 2 * pad)
    roi = frame[y:y2, x:x2]
    if roi.size:
        roi[:] = (roi * (1 - alpha) + np.array(bg, np.float32) * alpha).astype(np.uint8)
    cv2.putText(frame, text, (x + pad, y + pad + th), FONT, scale, fg, thick, cv2.LINE_AA)
    return y2 - y


def draw(frame: np.ndarray, index: int, t: float, hands: list[dict[str, Any]], objects: list[dict[str, Any]],
         events: list[tuple[str, float | None]], opts: dict[str, Any]) -> None:  # fmt: skip
    h, w = frame.shape[:2]
    s = h / 720
    if opts.get("objects", True):
        for o in objects:
            x, y = int(o["bbox_x"] * w), int(o["bbox_y"] * h)
            x2, y2 = int((o["bbox_x"] + o["bbox_w"]) * w), int((o["bbox_y"] + o["bbox_h"]) * h)
            cv2.rectangle(frame, (x, y), (x2, y2), WHITE, max(2, int(4 * s)), cv2.LINE_AA)
            cv2.rectangle(frame, (x, y), (x2, y2), OBJECT, max(1, int(2 * s)), cv2.LINE_AA)
            _label(
                frame,
                f"{o['label']} {o['score']:.2f}",
                (x, max(0, y - int(26 * s))),
                0.5 * s,
                WHITE,
                OBJECT,
                0.9,
            )
    if opts.get("skeleton", True):
        for hand in hands:
            pts = [(int(x * w), int(y * h)) for x, y in zip(hand["kp_x"], hand["kp_y"], strict=True)]
            for a, b in CONNECTIONS:
                cv2.line(frame, pts[a], pts[b], WHITE, max(3, int(5 * s)), cv2.LINE_AA)
                cv2.line(frame, pts[a], pts[b], SKELETON, max(2, int(3 * s)), cv2.LINE_AA)
            for p in pts:
                cv2.circle(frame, p, max(2, int(4 * s)), WHITE, -1, cv2.LINE_AA)
                cv2.circle(frame, p, max(1, int(3 * s)), SKELETON, -1, cv2.LINE_AA)
            wx, wy = pts[0]
            side = "L" if str(hand["handedness"]).lower().startswith("l") else "R"
            _label(frame, f"{side} #{hand['track_id']}", (max(0, wx - int(20 * s)), min(h - int(30 * s), wy + int(10 * s))),
                   0.5 * s, WHITE, SKELETON, 0.9)  # fmt: skip
    if opts.get("events", True):
        y = int(12 * s)
        for text, conf in events[:6]:
            y += _label(frame, text + (f"  {conf:.0%}" if conf is not None else "  corrected"), (int(12 * s), y),
                        0.62 * s, WHITE, INK) + int(6 * s)  # fmt: skip
    _label(frame, f"frame {index}  {t:6.2f} s", (int(12 * s), h - int(40 * s)), 0.5 * s, WHITE, INK)


def _events(db: Any, movement_run_id: uuid.UUID | None) -> list[tuple[int, int, str, float | None]]:
    if movement_run_id is None:
        return []
    rows = db.execute(
        select(MovementEvent, MovementClass.label)
        .join(MovementClass, MovementClass.id == MovementEvent.class_id)
        .where(
            MovementEvent.run_id == movement_run_id,
            MovementEvent.superseded_at.is_(None),
            MovementEvent.status != MovementEventStatus.rejected,
        )  # fmt: skip
        .order_by(MovementEvent.start_frame)
    ).all()
    out = []
    for e, label in rows:
        hand = f" · {e.handedness}" if e.handedness else ""
        obj = f" · {e.object_label}" if e.object_label else ""
        out.append((e.start_frame, e.end_frame, f"{label.upper()}{hand}{obj}", e.confidence))
    return out


def _encoder(dest: Path, w: int, h: int, fps: float, codec: str) -> list[str]:
    settings = get_settings()
    head = [settings.ffmpeg_bin, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}",
            "-r", f"{fps:.6f}", "-i", "pipe:0", "-an"]  # fmt: skip
    if codec == "vp9":
        return [*head, "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "34", "-row-mt", "1", "-deadline", "realtime",
                "-cpu-used", "8", "-pix_fmt", "yuv420p", str(dest)]  # fmt: skip
    return [*head, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(dest)]  # fmt: skip


def render(ctx: JobContext, video_id: uuid.UUID, *, hand_run_id: uuid.UUID | None, object_run_id: uuid.UUID | None,
           movement_run_id: uuid.UUID | None, options: dict[str, Any], user_id: uuid.UUID | None = None,
           annotated_video_id: uuid.UUID | None = None) -> dict[str, Any]:  # fmt: skip
    settings = get_settings()
    opts = {"max_side": 720, "codec": "h264", "skeleton": True, "objects": True, "events": True, **options}
    with ctx.session() as db:
        video = db.get(Video, video_id)
        if video is None:
            raise LookupError(f"video {video_id} not found")
        hand = db.get(CvRun, hand_run_id) if hand_run_id else None
        obj = db.get(CvRun, object_run_id) if object_run_id else None
        inputs = {"hand_run_id": str(hand_run_id) if hand_run_id else None,
                  "object_run_id": str(object_run_id) if object_run_id else None,
                  "movement_run_id": str(movement_run_id) if movement_run_id else None}  # fmt: skip
        av = db.get(AnnotatedVideo, annotated_video_id) if annotated_video_id else None
        if av is None:
            av = AnnotatedVideo(video_id=video.id, status=BuildStatus.building, created_by=user_id)
            db.add(av)
        av.inputs, av.options, av.job_id, av.status, av.error = (
            inputs,
            opts,
            ctx.job_id,
            BuildStatus.building,
            None,
        )
        db.commit()
        av_id = av.id
        events = _events(db, movement_run_id)
        hand_out, hand_stride = (dict(hand.output or {}), hand.stride) if hand else ({}, 1)
        obj_out, obj_stride = (dict(obj.output or {}), obj.stride) if obj else ({}, 1)
        width, height, fps = video.width or 0, video.height or 0, video.fps or 30.0
        key, kind, name = video.storage_key, video.source_kind, video.original_filename
        timestamps = frames_mod.video_timestamps(video)
    try:
        if not (width and height):
            raise ValueError("video has no known resolution")
        w, h = frames_mod.inference_size(width, height, int(opts["max_side"]))
        ext = "webm" if opts["codec"] == "vp9" else "mp4"
        ctx.info("Rendering annotated video", size=f"{w}x{h}", codec=opts["codec"], events=len(events),
                 hand_run_id=inputs["hand_run_id"], object_run_id=inputs["object_run_id"])  # fmt: skip
        hands = _Chunks(hand_out, "hands", ["frame", "track_id", "handedness", "kp_x", "kp_y"])
        objects = _Chunks(
            obj_out,
            "objects",
            ["frame", "track_id", "label", "score", "bbox_x", "bbox_y", "bbox_w", "bbox_h"],
        )
        with tempfile.TemporaryDirectory(dir=settings.work_dir, prefix="egolabs-render-") as tmp:
            work = Path(tmp)
            source, pattern = frames_mod.download_source(key, kind, work)
            dest = work / f"annotated.{ext}"
            decode = [settings.ffmpeg_bin, "-v", "error", "-nostdin", *input_args(source, pattern, fps), "-map", "0:v:0",
                      "-fps_mode", "passthrough", "-vf", f"scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"]  # fmt: skip
            dec = subprocess.Popen(decode, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            enc = subprocess.Popen(
                _encoder(dest, w, h, fps, opts["codec"]), stdin=subprocess.PIPE, stderr=subprocess.PIPE
            )
            assert dec.stdout is not None and enc.stdin is not None
            size, index = w * h * 3, 0
            held_h: list[dict[str, Any]] = []
            held_o: list[dict[str, Any]] = []
            try:
                while True:
                    buf = dec.stdout.read(size)
                    if len(buf) < size:
                        break
                    frame = np.frombuffer(buf, np.uint8).reshape(h, w, 3).copy()
                    if hand_out:
                        rows = hands.at(index)
                        if rows or index % hand_stride == 0:
                            held_h = rows
                    if obj_out:
                        rows = objects.at(index)
                        if rows or index % obj_stride == 0:
                            held_o = rows
                    active = [(text, conf) for a, b, text, conf in events if a <= index <= b]
                    t = timestamps[index] if index < len(timestamps) else index / fps
                    draw(frame, index, t, held_h, held_o, active, opts)
                    enc.stdin.write(frame.tobytes())
                    index += 1
                    if index % 1800 == 0:
                        ctx.info("Rendering", frames=index)
            finally:
                enc.stdin.close()
                dec.stdout.close()
                dec_err = dec.stderr.read().decode(errors="replace") if dec.stderr else ""
                dec.wait()
                enc_err = enc.stderr.read().decode(errors="replace") if enc.stderr else ""
                enc_code = enc.wait()
            if index == 0:
                raise frames_mod.FrameError(dec_err.strip()[:500] or "no frames decoded")
            if enc_code != 0:
                raise RuntimeError(f"encoding failed: {enc_err.strip()[:500]}")
            digest, nbytes = storage.sha256_file(dest), dest.stat().st_size
            out_key = f"annotated/{video_id}/{av_id}.{ext}"
            storage.upload(dest, settings.s3_bucket_derived, out_key, f"video/{ext}")
        with ctx.session() as db:
            row = db.get(AnnotatedVideo, av_id)
            assert row is not None
            row.status, row.storage_key, row.size_bytes, row.sha256 = (
                BuildStatus.ready,
                out_key,
                nbytes,
                digest,
            )
            row.codec, row.width, row.height, row.frames = opts["codec"], w, h, index
            row.duration_s, row.finished_at = round(index / fps, 3), datetime.now(UTC)
            db.add(LineageEdge(parent_type="video", parent_id=video_id, child_type="annotated_video", child_id=av_id,
                               relation="rendered_from", job_id=ctx.job_id))  # fmt: skip
            for rid in (hand_run_id, object_run_id, movement_run_id):
                if rid:
                    db.add(LineageEdge(parent_type="cv_run", parent_id=rid, child_type="annotated_video", child_id=av_id,
                                       relation="drawn_on", job_id=ctx.job_id))  # fmt: skip
            record_event(db, "video.annotated_rendered", f"Annotated video ready: {name}", entity_type="annotated_video",
                         entity_id=av_id, data={"video_id": str(video_id)})  # fmt: skip
            db.commit()
    except Exception as exc:
        with ctx.session() as db:
            row = db.get(AnnotatedVideo, av_id)
            if row is not None:
                row.status, row.error, row.finished_at = (
                    BuildStatus.failed,
                    str(exc)[:2000],
                    datetime.now(UTC),
                )
                db.commit()
        raise
    ctx.info("Annotated video stored", key=out_key, size_bytes=nbytes, frames=index, sha256=digest)
    return {"annotated_video_id": str(av_id), "storage_key": out_key, "size_bytes": nbytes, "frames": index,
            "width": w, "height": h, "codec": opts["codec"], "sha256": digest}  # fmt: skip


@job_handler("video.render_annotated")
def render_job(ctx: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
    """Render from the runs recorded on the annotated-video row (the API's "Render annotated video")."""
    with ctx.session() as db:
        av = db.get(AnnotatedVideo, uuid.UUID(payload["annotated_video_id"]))
        if av is None:
            raise LookupError(f"annotated video {payload['annotated_video_id']} not found")
        ids = {k: uuid.UUID(v) if v else None for k, v in (av.inputs or {}).items()}
        video_id, options, user_id = av.video_id, dict(av.options or {}), av.created_by
    return render(ctx, video_id, hand_run_id=ids.get("hand_run_id"), object_run_id=ids.get("object_run_id"),
                  movement_run_id=ids.get("movement_run_id"), options=options, user_id=user_id,
                  annotated_video_id=uuid.UUID(payload["annotated_video_id"]))  # fmt: skip
