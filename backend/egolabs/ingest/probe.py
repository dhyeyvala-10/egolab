"""ffprobe/ffmpeg wrappers. Every value returned here is read from the file — nothing is estimated."""

import json
import subprocess
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

from egolabs.config import get_settings

# Container/stream tags that describe the camera or capture, kept when present.
CAMERA_TAGS = {
    "make",
    "model",
    "software",
    "encoder",
    "creation_time",
    "location",
    "location-eng",
    "com.apple.quicktime.make",
    "com.apple.quicktime.model",
    "com.apple.quicktime.software",
    "com.apple.quicktime.creationdate",
    "com.apple.quicktime.location.iso6709",
    "com.android.manufacturer",
    "com.android.model",
    "com.android.version",
    "firmware",
    "device",
}


class ProbeError(Exception):
    """The file could not be read as media."""


@dataclass
class ProbeResult:
    duration_s: float | None
    width: int | None
    height: int | None
    fps: float | None
    codec: str | None
    frame_count: int | None
    bit_rate: int | None
    has_audio: bool
    camera_metadata: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


def _run(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise ProbeError(f"{Path(args[0]).name} timed out after {timeout}s") from exc


def _rate(value: str | None) -> float | None:
    if not value or value in ("0/0", "0"):
        return None
    try:
        rate = Fraction(value)
    except (ValueError, ZeroDivisionError):
        return None
    return round(float(rate), 6) if rate > 0 else None


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def ffprobe_json(path: Path, extra: list[str] | None = None, timeout: int = 120) -> dict[str, Any]:
    settings = get_settings()
    args = [settings.ffprobe_bin, "-v", "error", "-print_format", "json", "-show_format", "-show_streams"]
    proc = _run([*args, *(extra or []), str(path)], timeout)
    if proc.returncode != 0:
        raise ProbeError((proc.stderr or "ffprobe failed").strip()[:500])
    try:
        return json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise ProbeError("ffprobe returned invalid JSON") from exc


def count_frames(path: Path, timeout: int = 900) -> int | None:
    """Count video packets (one per frame) for containers that don't record a frame count."""
    settings = get_settings()
    proc = _run(
        [
            settings.ffprobe_bin, "-v", "error", "-select_streams", "v:0", "-count_packets",
            "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", str(path),
        ],
        timeout,
    )  # fmt: skip
    return _int(proc.stdout.strip().split(",")[0]) if proc.returncode == 0 else None


def probe(path: Path) -> ProbeResult:
    data = ffprobe_json(path)
    streams = data.get("streams", [])
    fmt = data.get("format", {})
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise ProbeError("no video stream")

    fps = _rate(video.get("avg_frame_rate")) or _rate(video.get("r_frame_rate"))
    frame_count = _int(video.get("nb_frames"))
    if frame_count is None:
        frame_count = count_frames(path)

    tags: dict[str, Any] = {}
    for source in (fmt.get("tags") or {}, video.get("tags") or {}):
        for key, value in source.items():
            if key.lower() in CAMERA_TAGS:
                tags[key.lower()] = value
    for side in video.get("side_data_list") or []:
        if "rotation" in side:
            tags["rotation"] = side["rotation"]
    if "rotate" in (video.get("tags") or {}):
        tags["rotation"] = _int(video["tags"]["rotate"])

    return ProbeResult(
        duration_s=_float(fmt.get("duration")) or _float(video.get("duration")),
        width=_int(video.get("width")),
        height=_int(video.get("height")),
        fps=fps,
        codec=video.get("codec_name"),
        frame_count=frame_count,
        bit_rate=_int(fmt.get("bit_rate")),
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
        camera_metadata=tags,
        raw=data,
    )


def decode_check(path: Path, seconds: float = 2.0, timeout: int = 120) -> None:
    """Decode the start of the stream; raise ProbeError if ffmpeg reports damage."""
    settings = get_settings()
    proc = _run(
        [settings.ffmpeg_bin, "-v", "error", "-xerror", "-t", str(seconds), "-i", str(path), "-map", "0:v:0",
         "-f", "null", "-"],
        timeout,
    )  # fmt: skip
    if proc.returncode != 0:
        raise ProbeError((proc.stderr or "decode failed").strip()[:500])


def tool_versions() -> dict[str, str]:
    settings = get_settings()
    versions = {}
    for name, binary in (("ffmpeg", settings.ffmpeg_bin), ("ffprobe", settings.ffprobe_bin)):
        proc = _run([binary, "-version"], 10)
        if proc.returncode != 0:
            raise ProbeError(f"{name} not available")
        versions[name] = proc.stdout.splitlines()[0] if proc.stdout else name
    return versions
