"""Decode video frames for inference: one RGB frame per source frame, in order, matching the proxy's numbering."""

import json
import subprocess
from collections.abc import Iterator
from pathlib import Path, PurePosixPath

import numpy as np

from egolabs import storage
from egolabs.config import get_settings
from egolabs.cv.adapters.base import Frame
from egolabs.ingest import frame_index
from egolabs.ingest.formats import extension
from egolabs.ingest.media import input_args
from egolabs.models import Video, VideoSource


class FrameError(Exception):
    pass


def video_timestamps(video: Video) -> list[float]:
    """Each frame's real timestamp from the frame index, or nominal ones from the FPS if it has none."""
    meta = (video.derivatives or {}).get("frame_index")
    if meta:
        try:
            index = json.loads(storage.get_bytes(get_settings().s3_bucket_derived, meta["key"]))
            return frame_index.timestamps(index)
        except Exception:  # noqa: BLE001 - fall back to nominal timing, recorded in the run stats
            pass
    fps = video.fps or 30.0
    return [i / fps for i in range(video.frame_count or 0)]


def download_source(key: str, kind: VideoSource, work: Path) -> tuple[Path, str | None]:
    """Fetch a video's raw media into `work`: (path, image-sequence file pattern or None)."""
    raw = get_settings().s3_bucket_raw
    if kind == VideoSource.image_sequence:
        source = work / "frames"
        source.mkdir()
        keys = storage.list_keys(raw, key)
        for k in keys:
            storage.download(raw, k, source / PurePosixPath(k).name)
        return source, f"%06d{extension(keys[0])}"
    source = work / f"source{extension(key)}"
    storage.download(raw, key, source)
    return source, None


def inference_size(width: int, height: int, max_side: int) -> tuple[int, int]:
    """Downscale so the long side is at most `max_side`, keeping even dimensions."""
    scale = min(1.0, max_side / max(width, height))
    w = max(2, int(round(width * scale / 2)) * 2)
    h = max(2, int(round(height * scale / 2)) * 2)
    return w, h


def _time(timestamps: list[float], index: int) -> float:
    if index < len(timestamps):
        return timestamps[index]
    # Past the known timestamps (or none known): continue at the last known spacing, or 30 fps.
    step = timestamps[-1] - timestamps[-2] if len(timestamps) >= 2 else 1 / 30
    last = timestamps[-1] if timestamps else -step
    return last + step * (index - len(timestamps) + 1)


def iter_frames(
    source: Path,
    *,
    width: int,
    height: int,
    timestamps: list[float],
    stride: int = 1,
    sequence_pattern: str | None = None,
    sequence_fps: float | None = None,
) -> Iterator[Frame]:
    """
    Yield every `stride`-th frame. Frame numbers and timestamps come from the frame index (`timestamps`),
    so they line up with the proxy the inspector plays.
    """
    settings = get_settings()
    w, h = inference_size(width, height, settings.cv_max_frame_side)
    cmd = [
        settings.ffmpeg_bin, "-v", "error", "-nostdin",
        *input_args(source, sequence_pattern, sequence_fps),
        "-map", "0:v:0", "-fps_mode", "passthrough",
        "-vf", f"scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
    ]  # fmt: skip
    size = w * h * 3
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdout is not None
    index = 0
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            if index % stride == 0:
                t = _time(timestamps, index)
                yield Frame(index=index, timestamp_s=t, image=np.frombuffer(buf, np.uint8).reshape(h, w, 3))
            index += 1
    finally:
        proc.stdout.close()
        err = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
        code = proc.wait()
    if code not in (0, None) and index == 0:
        raise FrameError(err.strip()[:500] or f"ffmpeg exited with {code}")
