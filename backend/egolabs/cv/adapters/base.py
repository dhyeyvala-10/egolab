"""
The model adapter interfaces (principle 10). Everything downstream — tracking, smoothing, kinematics,
storage, API, UI — sees only these types, so swapping a model is a configuration change.

Hand tracking (Phase 3) and object detection (Phase 4) share the pattern: `load(config)`, `predict(frames)`,
`metadata()`, plus optional `reset(video)` / `close()` hooks. The movement classifier interface is in
`egolabs.cv.movement.base`.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

Handedness = Literal["left", "right"]


@dataclass(frozen=True)
class Frame:
    index: int  # frame number in the video (matches the proxy and the frame index)
    timestamp_s: float
    image: np.ndarray  # H×W×3 uint8, RGB


@dataclass
class HandDetection:
    handedness: Handedness
    handedness_score: float  # the model's confidence in left/right
    confidence: float  # the model's confidence that this is a hand (0–1)
    # 21×3: x, y normalised to the frame, z relative depth (see egolabs.cv.keypoints)
    keypoints: np.ndarray
    # Per-keypoint confidence if the model gives one (21,), else None.
    keypoint_confidence: np.ndarray | None = None

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        """Tight box around the keypoints: x, y, width, height (normalised, clipped to the frame)."""
        xy = np.clip(self.keypoints[:, :2], 0.0, 1.0)
        x0, y0 = xy.min(axis=0)
        x1, y1 = xy.max(axis=0)
        return float(x0), float(y0), float(x1 - x0), float(y1 - y0)


@dataclass
class HandResult:
    frame_index: int
    timestamp_s: float
    hands: list[HandDetection] = field(default_factory=list)


@dataclass(frozen=True)
class VideoContext:
    """The video about to be processed, passed to `reset`."""

    video_id: str
    sha256: str
    width: int | None
    height: int | None
    fps: float | None
    frame_count: int | None


@dataclass(frozen=True)
class AdapterMetadata:
    name: str  # e.g. mediapipe-hands
    version: str  # model + runtime version, e.g. hand_landmarker@2ed44f10 mediapipe-1.0.1
    keypoint_schema: dict[str, Any] | None = None  # hand models
    labels: list[str] | None = None  # object detectors: the labels they can output; classifiers: classes


class HandTrackingAdapter(ABC):
    """
    A hand keypoint model.

    `predict` is called with consecutive batches of frames in order, so an adapter may keep temporal state
    (e.g. a detector that tracks between frames); `reset(video)` is called before each new video. Output
    keypoints must follow `egolabs.cv.keypoints` (21 points). Frames with no hands return an empty list.
    """

    kind = "hand_tracking"

    @abstractmethod
    def load(self, config: dict[str, Any]) -> None: ...

    @abstractmethod
    def predict(self, frames: Sequence[Frame]) -> list[HandResult]: ...

    @abstractmethod
    def metadata(self) -> AdapterMetadata: ...

    def reset(self, video: VideoContext | None = None) -> None:  # noqa: B027 - optional hook
        """Forget temporal state before a new video."""

    def close(self) -> None:  # noqa: B027 - optional hook
        """Release model resources."""


@dataclass
class ObjectDetection:
    label: str  # e.g. "cup" (the detector's own label set)
    score: float  # 0–1
    bbox: tuple[float, float, float, float]  # x, y, width, height, normalised to the frame


@dataclass
class ObjectResult:
    frame_index: int
    timestamp_s: float
    objects: list[ObjectDetection] = field(default_factory=list)


class ObjectDetectionAdapter(ABC):
    """
    An object detector. `predict` gets consecutive batches of frames in order (so a detector may track
    between frames) and returns one result per frame, with an empty list when nothing is found.
    """

    kind = "object_detection"

    @abstractmethod
    def load(self, config: dict[str, Any]) -> None: ...

    @abstractmethod
    def predict(self, frames: Sequence[Frame]) -> list[ObjectResult]: ...

    @abstractmethod
    def metadata(self) -> AdapterMetadata: ...

    def reset(self, video: VideoContext | None = None) -> None:  # noqa: B027 - optional hook
        """Forget temporal state before a new video."""

    def close(self) -> None:  # noqa: B027 - optional hook
        """Release model resources."""


class AdapterError(Exception):
    pass
