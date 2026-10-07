"""
Movement events produced elsewhere — a learned model run outside Ego Labs — read from JSON Lines, one event
per line:

    {"class": "grasp", "track_id": 1, "frames": [40, 41, 42], "confidence": 0.87,
     "fingers": ["thumb", "index"], "object_track_id": 2, "attributes": {...}}

`track_id` is the hand track in the hand-tracking run being classified, `frames` the frames of that track
the model based the event on. `source` is a local path or `s3://bucket/key` URL and may contain `{sha256}`
or `{video_id}`; `name` and `version` identify the model.
"""

import json
from collections.abc import Sequence
from typing import Any

from egolabs.cv.adapters import sources
from egolabs.cv.adapters.base import AdapterError, AdapterMetadata, VideoContext
from egolabs.cv.movement.base import MotionFrame, MovementClassifier, MovementDetection


class EventsFileClassifier(MovementClassifier):
    def __init__(self) -> None:
        self._config: dict[str, Any] = {}
        self._events: list[dict[str, Any]] = []
        self._handedness: dict[int, str] = {}
        self._labels: dict[int, str] = {}

    def load(self, config: dict[str, Any]) -> None:
        missing = {"source", "name", "version"} - set(config)
        if missing:
            raise AdapterError(
                f"events-file needs: {', '.join(sorted(missing))} (name/version identify the model)"
            )
        self._config = dict(config)

    def metadata(self) -> AdapterMetadata:
        return AdapterMetadata(name=str(self._config.get("name", "events-file")),
                               version=str(self._config.get("version", "unknown")))  # fmt: skip

    def reset(self, video: VideoContext | None = None) -> None:
        self._events, self._handedness, self._labels = [], {}, {}
        if video is None:
            return
        source = sources.resolve(str(self._config["source"]), video)
        for n, line in enumerate(sources.read_text(source).splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                frames = sorted({int(f) for f in row["frames"]})
                if not frames:
                    raise ValueError("frames is empty")
                self._events.append({**row, "frames": frames, "track_id": int(row["track_id"]),
                                     "confidence": float(row["confidence"]), "class": str(row["class"])})  # fmt: skip
            except (KeyError, TypeError, ValueError) as exc:
                raise AdapterError(f"{source} line {n}: {exc}") from exc

    def predict(self, frames: Sequence[MotionFrame]) -> list[MovementDetection]:
        for frame in frames:  # learn each track's handedness and the objects' labels
            for hand in frame.hands:
                self._handedness.setdefault(hand.track_id, hand.handedness)
            for obj in frame.objects:
                self._labels.setdefault(obj.track_id, obj.label)
        return []

    def finish(self) -> list[MovementDetection]:
        out = []
        for e in self._events:
            obj = e.get("object_track_id")
            out.append(
                MovementDetection(
                    name=e["class"],
                    hand_track_id=e["track_id"],
                    handedness=self._handedness.get(e["track_id"], "unknown"),
                    frames=e["frames"],
                    confidence=max(0.0, min(1.0, e["confidence"])),
                    fingers=tuple(e.get("fingers", ())),
                    object_track_id=int(obj) if obj is not None else None,
                    object_label=self._labels.get(int(obj)) if obj is not None else None,
                    rule=f"from {self._config.get('name')}",
                    attributes=dict(e.get("attributes", {})),
                )  # fmt: skip
            )
        return out
