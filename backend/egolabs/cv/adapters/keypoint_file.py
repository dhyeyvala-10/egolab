"""
Keypoints produced elsewhere — by a model run outside Ego Labs, or an earlier export — read from JSON Lines.

One line per frame that has hands (other frames have none):

    {"frame": 12, "hands": [{"handedness": "right", "confidence": 0.93, "keypoints": [[x, y, z], … 21]}]}

Keypoints use the hand-21 schema, normalised to the frame. `source` is a local path or an `s3://bucket/key`
URL and may contain `{sha256}` or `{video_id}`, so one configuration covers every video.
"""

import json
from collections.abc import Sequence
from typing import Any

import numpy as np

from egolabs.cv import keypoints
from egolabs.cv.adapters import sources
from egolabs.cv.adapters.base import (
    AdapterError,
    AdapterMetadata,
    Frame,
    HandDetection,
    HandResult,
    HandTrackingAdapter,
    VideoContext,
)


class KeypointFileAdapter(HandTrackingAdapter):
    def __init__(self) -> None:
        self._config: dict[str, Any] = {}
        self._by_frame: dict[int, list[HandDetection]] = {}

    def load(self, config: dict[str, Any]) -> None:
        missing = {"source", "name", "version"} - set(config)
        if missing:
            raise AdapterError(
                f"keypoint-file needs: {', '.join(sorted(missing))} (name/version identify the model)"
            )
        self._config = dict(config)

    def metadata(self) -> AdapterMetadata:
        return AdapterMetadata(
            name=str(self._config.get("name", "keypoint-file")),
            version=str(self._config.get("version", "unknown")),
            keypoint_schema=keypoints.SCHEMA,
        )

    def reset(self, video: VideoContext | None = None) -> None:
        self._by_frame = {}
        if video is None:
            return
        source = sources.resolve(str(self._config["source"]), video)
        for n, line in enumerate(sources.read_text(source).splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                hands = [
                    HandDetection(
                        handedness=h["handedness"],
                        handedness_score=float(h.get("handedness_score", h["confidence"])),
                        confidence=float(h["confidence"]),
                        keypoints=np.asarray(h["keypoints"], dtype=np.float32).reshape(21, 3),
                    )
                    for h in row["hands"]
                ]
            except (KeyError, TypeError, ValueError) as exc:
                raise AdapterError(f"{source} line {n}: {exc}") from exc
            if any(h.handedness not in ("left", "right") for h in hands):
                raise AdapterError(f"{source} line {n}: handedness must be left or right")
            self._by_frame[int(row["frame"])] = hands

    def predict(self, frames: Sequence[Frame]) -> list[HandResult]:
        return [HandResult(f.index, f.timestamp_s, list(self._by_frame.get(f.index, []))) for f in frames]
