"""
The movement classifier interface — the same adapter pattern as hand tracking and object detection
(`load(config)`, `predict(frames)`, `metadata()`), so a learned model can replace the rules by configuration.

A classifier sees a stream of `MotionFrame`s: the tracked hands (keypoints and kinematics from a
hand-tracking run), the tracked objects (from an object-detection run, if any), and the hand–object
contacts computed from both. It returns `MovementDetection`s, each naming the exact frames it was derived
from (`frames`) and the per-frame values the decision was based on (`measurements`), so every event can be
traced back to its keypoints.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from egolabs.cv.adapters.base import AdapterMetadata, VideoContext


@dataclass
class HandState:
    track_id: int
    handedness: str
    confidence: float
    keypoints: np.ndarray  # 21×3 smoothed; x, y normalised to the frame, z relative depth on x's scale
    wrist_velocity: tuple[float, float]  # source px/s
    tip_speed: dict[str, float]  # fingertip speed per finger, source px/s


@dataclass
class ObjectState:
    track_id: int
    label: str
    score: float
    bbox: tuple[float, float, float, float]  # x, y, w, h normalised


@dataclass
class Contact:
    """A hand touching an object in this frame (estimated from 2-D overlap, see egolabs.cv.movement.contact)."""

    hand_track_id: int
    object_track_id: int
    fingers: tuple[str, ...]  # fingertips over the object
    score: float  # 0–1: share of the hand's fingertips on the object, weighted by the object's score


@dataclass
class MotionFrame:
    index: int
    timestamp_s: float
    hands: list[HandState] = field(default_factory=list)
    objects: list[ObjectState] = field(default_factory=list)
    contacts: list[Contact] = field(default_factory=list)


@dataclass
class MovementDetection:
    name: str  # movement class name, e.g. "pinch" (see the movement_classes table)
    hand_track_id: int
    handedness: str
    frames: list[int]  # the processed frames the decision used, ascending
    confidence: float  # 0–1
    fingers: tuple[str, ...] = ()
    object_track_id: int | None = None
    object_label: str | None = None
    # name → one value per entry of `frames` (e.g. thumb–index distance / hand size)
    measurements: dict[str, list[float]] = field(default_factory=dict)
    thresholds: dict[str, float] = field(default_factory=dict)
    rule: str = ""  # human-readable statement of the rule that fired
    attributes: dict[str, Any] = field(default_factory=dict)  # e.g. {"direction": "left"}

    @property
    def start_frame(self) -> int:
        return self.frames[0]

    @property
    def end_frame(self) -> int:
        return self.frames[-1]


class MovementClassifier(ABC):
    """
    Turns motion into movement events. `reset(video)` comes before each video; `predict` gets consecutive
    batches of frames in order and returns the events that have finished; `finish()` returns the rest at the
    end of the video. Classifiers may keep temporal state between calls.
    """

    kind = "movement"
    # Class names this classifier can emit (shown in the UI; a class outside the table becomes a custom class).
    classes: tuple[str, ...] = ()

    @abstractmethod
    def load(self, config: dict[str, Any]) -> None: ...

    @abstractmethod
    def predict(self, frames: Sequence[MotionFrame]) -> list[MovementDetection]: ...

    @abstractmethod
    def metadata(self) -> AdapterMetadata: ...

    def reset(self, video: VideoContext | None = None) -> None:  # noqa: B027 - optional hook
        """Forget temporal state before a new video."""

    def finish(self) -> list[MovementDetection]:
        """Events still open when the video ends."""
        return []

    def close(self) -> None:  # noqa: B027 - optional hook
        """Release model resources."""
