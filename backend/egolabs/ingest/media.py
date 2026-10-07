"""Derived media for fast playback: a low-res proxy and a thumbnail strip. Raw files are never modified."""

import subprocess
from pathlib import Path
from typing import Any

from egolabs.config import get_settings

PROXY_HEIGHT = 360
THUMB_COUNT = 10
THUMB_WIDTH = 160


# Both avoid reordered or hidden frames, so each packet is one displayed frame in presentation order.
PROXY_CODECS = {
    "h264": ["-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p",
             "-bf", "0", "-sc_threshold", "0"],
    "vp9": ["-c:v", "libvpx-vp9", "-crf", "36", "-b:v", "0", "-deadline", "realtime", "-cpu-used", "8",
            "-row-mt", "1", "-lag-in-frames", "0", "-auto-alt-ref", "0", "-pix_fmt", "yuv420p"],
}  # fmt: skip


class MediaError(Exception):
    pass


def _ffmpeg(args: list[str], timeout: int) -> None:
    settings = get_settings()
    try:
        proc = subprocess.run(
            [settings.ffmpeg_bin, "-y", "-v", "error", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise MediaError(f"ffmpeg timed out after {timeout}s") from exc
    if proc.returncode != 0:
        raise MediaError((proc.stderr or "ffmpeg failed").strip()[:500])


def input_args(source: Path, sequence_pattern: str | None, sequence_fps: float | None) -> list[str]:
    if sequence_pattern is None:
        return ["-i", str(source)]
    # Image sequences have no timing of their own; play frames at the user-given rate (or 30 for preview).
    return ["-framerate", str(sequence_fps or 30), "-start_number", "1", "-i", str(source / sequence_pattern)]


def make_proxy(
    source: Path,
    dest: Path,
    *,
    sequence_pattern: str | None = None,
    sequence_fps: float | None = None,
    timeout: int = 3600,
) -> dict[str, Any]:
    """
    360p proxy (H.264 by default) with one output frame per source frame (no drops or duplicates), a keyframe every
    30 frames, and no B-frames (so decode order is presentation order and there is no start offset),
    so the inspector can seek to exact frame indices using the frame index.
    """
    codec = get_settings().proxy_codec
    codec_args = PROXY_CODECS[codec]
    _ffmpeg(
        [
            *input_args(source, sequence_pattern, sequence_fps),
            "-map", "0:v:0", "-an",
            "-vf", f"scale=-2:{PROXY_HEIGHT}",
            "-fps_mode", "passthrough",
            *codec_args,
            "-g", "30", "-keyint_min", "30",
            "-movflags", "+faststart",
            str(dest),
        ],
        timeout,
    )  # fmt: skip
    return {"height": PROXY_HEIGHT, "codec": codec, "gop": 30, "b_frames": 0, "fps_mode": "passthrough"}


def make_thumbnail_strip(
    source: Path,
    dest: Path,
    *,
    duration_s: float | None,
    frame_count: int | None,
    sequence_pattern: str | None = None,
    sequence_fps: float | None = None,
    timeout: int = 900,
) -> dict[str, Any]:
    """A single JPEG of THUMB_COUNT evenly spaced frames, left to right."""
    if frame_count and frame_count > 0:
        step = max(1, frame_count // THUMB_COUNT)
        select = f"select='not(mod(n\\,{step}))'"
    elif duration_s and duration_s > 0:
        select = f"fps={THUMB_COUNT}/{duration_s:.3f}"
    else:
        select = "select='not(mod(n\\,30))'"
    _ffmpeg(
        [
            *input_args(source, sequence_pattern, sequence_fps),
            "-map", "0:v:0",
            "-vf", f"{select},scale={THUMB_WIDTH}:-2,tile={THUMB_COUNT}x1",
            "-fps_mode", "vfr", "-frames:v", "1", "-q:v", "4",
            str(dest),
        ],
        timeout,
    )  # fmt: skip
    return {"count": THUMB_COUNT, "tile": f"{THUMB_COUNT}x1", "thumb_width": THUMB_WIDTH}
