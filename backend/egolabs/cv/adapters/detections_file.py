"""
Object detections produced elsewhere, read from JSON Lines — one line per frame with objects:

    {"frame": 12, "objects": [{"label": "cup", "score": 0.91, "bbox": [x, y, w, h]}]}

Boxes are normalised to the frame (origin top left). `source` is a local path or an `s3://bucket/key` URL
and may contain `{sha256}` or `{video_id}`; `name` and `version` identify the model that made them.
"""

import json
from collections.abc import Sequence
from typing import Any

from egolabs.cv.adapters import sources
from egolabs.cv.adapters.base import (
    AdapterError,
    AdapterMetadata,
    Frame,
    ObjectDetection,
    ObjectDetectionAdapter,
    ObjectResult,
    VideoContext,
)


class DetectionsFileAdapter(ObjectDetectionAdapter):
    def __init__(self) -> None:
        self._config: dict[str, Any] = {}
        self._by_frame: dict[int, list[ObjectDetection]] = {}

    def load(self, config: dict[str, Any]) -> None:
        missing = {"source", "name", "version"} - set(config)
        if missing:
            raise AdapterError(
                f"detections-file needs: {', '.join(sorted(missing))} (name/version identify the model)"
            )
        self._config = dict(config)

    def metadata(self) -> AdapterMetadata:
        return AdapterMetadata(
            name=str(self._config.get("name", "detections-file")),
            version=str(self._config.get("version", "unknown")),
            labels=self._config.get("labels"),
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
                objects = []
                for o in row["objects"]:
                    x, y, w, h = (float(v) for v in o["bbox"])
                    if not (
                        0 <= x <= 1
                        and 0 <= y <= 1
                        and w > 0
                        and h > 0
                        and x + w <= 1.0001
                        and y + h <= 1.0001
                    ):
                        raise ValueError(f"bbox {o['bbox']} is not a normalised box inside the frame")
                    objects.append(
                        ObjectDetection(label=str(o["label"]), score=float(o["score"]), bbox=(x, y, w, h))
                    )
            except (KeyError, TypeError, ValueError) as exc:
                raise AdapterError(f"{source} line {n}: {exc}") from exc
            self._by_frame[int(row["frame"])] = objects

    def predict(self, frames: Sequence[Frame]) -> list[ObjectResult]:
        return [ObjectResult(f.index, f.timestamp_s, list(self._by_frame.get(f.index, []))) for f in frames]
