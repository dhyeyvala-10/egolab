"""
Frame index: the presentation timestamp of every frame in a video's proxy.

The inspector plays the proxy and seeks by frame number. Nominal FPS is not enough for that: variable
frame rate sources, and containers whose timestamps drift from their stated rate, would put frame N
somewhere near N / fps rather than at it. The index records each frame's real timestamp (read from
the proxy's packets, no decode needed), run-length encoded so a constant-rate 30-minute video is
one run instead of 54,000 numbers.

    {"version": 1, "frame_count": 54000, "time_base": [1, 15360],
     "runs": [[start_pts, step, count], ...]}

Frame i's timestamp in seconds is `pts_i * time_base[0] / time_base[1]`, where `pts_i` comes from the
run containing i: `start_pts + step * (i - frames before the run)`.
"""

import json
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Any

from egolabs.config import get_settings

VERSION = 1


class FrameIndexError(Exception):
    pass


def encode_runs(pts: list[int]) -> list[list[int]]:
    """Run-length encode sorted timestamps as [start, step, count] triples."""
    runs: list[list[int]] = []
    i = 0
    while i < len(pts):
        start = pts[i]
        if i + 1 == len(pts):
            runs.append([start, 0, 1])
            break
        step = pts[i + 1] - start
        j = i + 1
        while j + 1 < len(pts) and pts[j + 1] - pts[j] == step:
            j += 1
        runs.append([start, step, j - i + 1])
        i = j + 1
    return runs


def decode_runs(runs: list[list[int]]) -> list[int]:
    return [start + step * k for start, step, count in runs for k in range(count)]


def build(proxy: Path, timeout: int = 900) -> dict[str, Any]:
    """Read every video packet's timestamp from the proxy, in presentation order."""
    settings = get_settings()
    args = [
        settings.ffprobe_bin, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=time_base:packet=pts", "-of", "json", str(proxy),
    ]  # fmt: skip
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise FrameIndexError(f"ffprobe timed out after {timeout}s") from exc
    if proc.returncode != 0:
        raise FrameIndexError((proc.stderr or "ffprobe failed").strip()[:500])
    data = json.loads(proc.stdout or "{}")
    streams = data.get("streams") or []
    if not streams:
        raise FrameIndexError("proxy has no video stream")
    time_base = Fraction(streams[0]["time_base"])
    pts = sorted(int(p["pts"]) for p in data.get("packets", []) if p.get("pts") not in (None, "N/A"))
    if not pts:
        raise FrameIndexError("proxy has no timestamped frames")
    if len(set(pts)) != len(pts):
        raise FrameIndexError("proxy has frames with duplicate timestamps")
    return {
        "version": VERSION,
        "frame_count": len(pts),
        "time_base": [time_base.numerator, time_base.denominator],
        "runs": encode_runs(pts),
    }


def timestamps(index: dict[str, Any]) -> list[float]:
    num, den = index["time_base"]
    return [p * num / den for p in decode_runs(index["runs"])]


def seek_time(times: list[float], frame: int) -> float:
    """
    Where to seek so frame `frame` is on screen: halfway into its display interval. Browsers show the
    frame whose timestamp is the last one at or before `currentTime`, so the midpoint is safe against
    rounding either way. Mirrors `seekTime` in web/lib/inspector/frames.ts.
    """
    t = times[frame]
    if frame + 1 < len(times):
        return (t + times[frame + 1]) / 2
    step = times[frame] - times[frame - 1] if frame > 0 else 1 / 30
    return t + step / 2


def summary(index: dict[str, Any], key: str) -> dict[str, Any]:
    return {"key": key, "version": index["version"], "frame_count": index["frame_count"],
            "runs": len(index["runs"])}  # fmt: skip
