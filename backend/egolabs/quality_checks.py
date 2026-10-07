"""
Quality-check steps (spec Phase 7): blur, low light, occlusion, and near-duplicates. Each measures the
video, stores the measurements and the thresholds it was held to (`video_quality_checks`), and sets or
clears its flag on the video, which the dataset builder can leave out.

- **Blur:** variance of the Laplacian of sampled frames, scaled to 640 px wide (low = few sharp edges).
- **Low light:** mean brightness (0–255) of sampled frames.
- **Occlusion:** the share of the hand run's finger observations marked occluded.
- **Near-duplicates:** a 64-bit difference hash per sampled frame. Another video is a near-duplicate when
  enough of this video's frames have a hash within `max_distance` bits of one of its frames. Candidates come
  from the four indexed 16-bit bands, probed exactly and with each bit flipped, so every pair within 7 bits
  is found without scanning all hashes.
"""

import subprocess
import tempfile
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import delete, or_, select

from egolabs.config import get_settings
from egolabs.cv import frames as frames_mod
from egolabs.events import record_event
from egolabs.ingest.media import input_args
from egolabs.models import CvRun, Video, VideoFrameHash, VideoQualityCheck
from egolabs.worker.runtime import JobContext

FLAG = {
    "blur": "blurry",
    "low_light": "low_light",
    "occlusion": "high_occlusion",
    "duplicates": "near_duplicate",
}
MAX_SAMPLES = 600
TIMES_KEPT = 200


def _even(v: float) -> int:
    return max(2, int(round(v / 2)) * 2)


def sample_gray(
    video: Video, work: Path, sample_fps: float, width: int, height: int | None = None
) -> Iterator[tuple[float, np.ndarray]]:
    """Grayscale frames sampled at `sample_fps` (at most MAX_SAMPLES over the video), as (time s, array)."""
    settings = get_settings()
    source, pattern = frames_mod.download_source(video.storage_key, video.source_kind, work)
    duration = video.duration_s or ((video.frame_count or 0) / (video.fps or 30.0))
    fps = min(sample_fps, MAX_SAMPLES / duration) if duration else sample_fps
    w = width
    h = height or _even(width * (video.height or 9) / (video.width or 16))
    cmd = [
        settings.ffmpeg_bin, "-v", "error", "-nostdin", *input_args(source, pattern, video.fps),
        "-map", "0:v:0", "-vf", f"fps={fps:.6f},scale={w}:{h}:flags=area,format=gray",
        "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1",
    ]  # fmt: skip
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdout is not None
    size, i = w * h, 0
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            yield i / fps, np.frombuffer(buf, np.uint8).reshape(h, w)
            i += 1
    finally:
        proc.stdout.close()
        err = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
        code = proc.wait()
    if code not in (0, None) and i == 0:
        raise frames_mod.FrameError(err.strip()[:500] or f"ffmpeg exited with {code}")


def sharpness(gray: np.ndarray) -> float:
    """Variance of the 4-neighbour Laplacian."""
    g = gray.astype(np.float32)
    lap = g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:] - 4 * g[1:-1, 1:-1]
    return float(lap.var())


def dhash(gray9x8: np.ndarray) -> int:
    """64-bit difference hash of a 9×8 grayscale image: each bit is whether a pixel is brighter than the next."""
    bits = gray9x8[:, 1:] > gray9x8[:, :-1]
    return int("".join("1" if b else "0" for b in bits.flatten()), 2)


def signed(h: int) -> int:
    return h - (1 << 64) if h >= 1 << 63 else h


def bands(h: int) -> list[int]:
    return [(h >> (16 * i)) & 0xFFFF for i in range(4)]


def _summary(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"median": None, "p10": None, "p90": None}
    a = np.asarray(values)
    return {"median": round(float(np.median(a)), 2), "p10": round(float(np.percentile(a, 10)), 2),
            "p90": round(float(np.percentile(a, 90)), 2)}  # fmt: skip


def _frames_check(video: Video, config: dict[str, Any], measure: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(dir=get_settings().work_dir, prefix="egolabs-quality-") as tmp:
        values, times = [], []
        for t, g in sample_gray(video, Path(tmp), config["sample_fps"], 640):
            values.append(sharpness(g) if measure == "blur" else float(g.mean()))
            times.append(t)
    if not values:
        raise frames_mod.FrameError("no frames could be sampled")
    if measure == "blur":
        bad = [t for t, v in zip(times, values, strict=True) if v < config["threshold"]]
        name, limit = "sharpness", config["threshold"]
    else:
        bad = [t for t, v in zip(times, values, strict=True) if v < config["luma_threshold"]]
        name, limit = "brightness", config["luma_threshold"]
    fraction = len(bad) / len(values)
    return {"samples": len(values), "below_threshold": len(bad), "fraction": round(fraction, 4), "threshold": limit,
            name: _summary(values), "times_below_s": [round(t, 2) for t in bad[:TIMES_KEPT]],
            "flagged": fraction > config["max_fraction"]}  # fmt: skip


def _occlusion(db: Any, hand_run_id: uuid.UUID, config: dict[str, Any]) -> dict[str, Any]:
    from egolabs.cv import store

    run = db.get(CvRun, hand_run_id)
    assert run is not None
    total = occluded = 0
    per: dict[str, list[int]] = {}
    for key in (run.output or {}).get("fingers", []):
        t = store.read_part(key).select(["finger", "occluded"])
        fingers = t["finger"].to_pylist()
        occ = t["occluded"].to_pylist()
        for f, o in zip(fingers, occ, strict=True):
            c = per.setdefault(f, [0, 0])
            c[0] += 1
            c[1] += int(bool(o))
        total += len(occ)
        occluded += sum(1 for o in occ if o)
    rate = occluded / total if total else None
    return {"hand_run_id": str(hand_run_id), "finger_observations": total, "occluded": occluded,
            "rate": round(rate, 4) if rate is not None else None, "max_rate": config["max_rate"],
            "fingers": {f: round(c[1] / c[0], 4) for f, c in sorted(per.items()) if c[0]},
            "note": None if total else "no hands were tracked, so there is nothing to measure",
            "flagged": bool(rate is not None and rate > config["max_rate"])}  # fmt: skip


def _probe_values(band: int) -> list[int]:
    return [band] + [band ^ (1 << b) for b in range(16)]


def _duplicates(db: Any, ctx: JobContext, video: Video, config: dict[str, Any]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(dir=get_settings().work_dir, prefix="egolabs-dhash-") as tmp:
        hashes = [
            (i, dhash(g))
            for i, (_, g) in enumerate(sample_gray(video, Path(tmp), config["sample_fps"], 9, 8))
        ]
    if not hashes:
        raise frames_mod.FrameError("no frames could be sampled")
    db.execute(delete(VideoFrameHash).where(VideoFrameHash.video_id == video.id))
    db.add_all([VideoFrameHash(video_id=video.id, frame=i, hash=signed(h), **{f"b{k}": b for k, b in enumerate(bands(h))})
                for i, h in hashes])  # fmt: skip
    db.flush()
    probes: list[set[int]] = [set() for _ in range(4)]
    for _, h in hashes:
        for k, b in enumerate(bands(h)):
            probes[k].update(_probe_values(b))
    cols = [VideoFrameHash.b0, VideoFrameHash.b1, VideoFrameHash.b2, VideoFrameHash.b3]
    rows = db.execute(
        select(VideoFrameHash.video_id, VideoFrameHash.hash)
        .where(VideoFrameHash.video_id != video.id, or_(*[c.in_(sorted(p)) for c, p in zip(cols, probes, strict=True)]))
    ).all()  # fmt: skip
    by_video: dict[uuid.UUID, list[int]] = {}
    for vid, h in rows:
        by_video.setdefault(vid, []).append(h & ((1 << 64) - 1))
    matches = []
    for vid, theirs in by_video.items():
        matched = sum(
            1 for _, h in hashes if any(bin(h ^ o).count("1") <= config["max_distance"] for o in theirs)
        )
        overlap = matched / len(hashes)
        if overlap >= config["min_overlap"]:
            other = db.get(Video, vid)
            matches.append({"video_id": str(vid), "name": other.original_filename if other else None,
                            "matched_frames": matched, "overlap": round(overlap, 4)})  # fmt: skip
            if other is not None and FLAG["duplicates"] not in (other.quality_flags or []):
                other.quality_flags = sorted({*(other.quality_flags or []), FLAG["duplicates"]})
                ctx.info("Flagged the other video as a near-duplicate too", video=other.original_filename)
    matches.sort(key=lambda m: -m["overlap"])
    return {"samples": len(hashes), "candidates": len(by_video), "max_distance": config["max_distance"],
            "min_overlap": config["min_overlap"], "matches": matches[:50], "flagged": bool(matches)}  # fmt: skip


def run(ctx: JobContext, check: str, video_id: uuid.UUID, config: dict[str, Any], *,
        hand_run_id: uuid.UUID | None = None) -> dict[str, Any]:  # fmt: skip
    flag = FLAG[check]
    with ctx.session() as db:
        video = db.get(Video, video_id)
        if video is None:
            raise LookupError(f"video {video_id} not found")
        if check in ("blur", "low_light"):
            metrics = _frames_check(video, config, check)
        elif check == "occlusion":
            assert hand_run_id is not None
            metrics = _occlusion(db, hand_run_id, config)
        else:
            metrics = _duplicates(db, ctx, video, config)
        flagged = bool(metrics.pop("flagged"))
        row = VideoQualityCheck(video_id=video.id, check=check, flag=flag, flagged=flagged, metrics=metrics,
                                config=config, job_id=ctx.job_id)  # fmt: skip
        db.add(row)
        before = set(video.quality_flags or [])
        after = (before | {flag}) if flagged else (before - {flag})
        video.quality_flags = sorted(after)
        if flagged and flag not in before:
            record_event(db, "video.quality_flagged", f"{video.original_filename} flagged {flag}", entity_type="video",
                         entity_id=video.id, data={"check": check})  # fmt: skip
        db.commit()
        check_id = row.id
    level = "warning" if flagged else "info"
    ctx.log(level, f"{check.replace('_', ' ').capitalize()} check: {'flagged ' + flag if flagged else 'passed'}",
            check=check, **{k: v for k, v in metrics.items() if isinstance(v, int | float | str) and v is not None})  # fmt: skip
    return {"check_id": str(check_id), "check": check, "flag": flag, "flagged": flagged, "metrics": metrics,
            "checked_at": datetime.now(UTC).isoformat()}  # fmt: skip
