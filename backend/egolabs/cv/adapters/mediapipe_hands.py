"""MediaPipe Hands (HandLandmarker): palm detection + 21-keypoint estimation, on CPU."""

from collections.abc import Sequence
from importlib.metadata import version as package_version
from typing import Any

import numpy as np

from egolabs.cv import keypoints
from egolabs.cv.adapters.base import (
    AdapterError,
    AdapterMetadata,
    Frame,
    HandDetection,
    HandResult,
    HandTrackingAdapter,
    VideoContext,
)
from egolabs.cv.assets import HAND_LANDMARKER, ensure

DEFAULTS: dict[str, Any] = {
    "num_hands": 2,
    "min_hand_detection_confidence": 0.5,
    "min_hand_presence_confidence": 0.5,
    "min_tracking_confidence": 0.5,
    # "video" reuses the previous frame's hand region (faster, steadier); "image" detects every frame afresh.
    "running_mode": "video",
    # MediaPipe's left/right labels are correct for ordinary (unmirrored) footage such as head-mounted
    # cameras. Set true for selfie-style mirrored input.
    "mirrored_input": False,
    "model_path": None,  # default: the pinned hand_landmarker.task, downloaded and checksummed on first use
}


class MediaPipeHands(HandTrackingAdapter):
    def __init__(self) -> None:
        self._landmarker: Any = None
        self._given: dict[str, Any] = {}
        self._config: dict[str, Any] = {}
        self._last_ms = -1

    def load(self, config: dict[str, Any]) -> None:
        unknown = set(config) - set(DEFAULTS)
        if unknown:
            raise AdapterError(f"unknown mediapipe-hands options: {', '.join(sorted(unknown))}")
        self._given = dict(config)
        self._config = {**DEFAULTS, **config}
        if self._config["running_mode"] not in ("video", "image"):
            raise AdapterError("running_mode must be 'video' or 'image'")
        try:
            from mediapipe.tasks.python import BaseOptions, vision
        except ImportError as exc:  # pragma: no cover - dependency is required in the image
            raise AdapterError("mediapipe is not installed") from exc
        model = self._config["model_path"] or str(ensure(HAND_LANDMARKER))
        mode = (
            vision.RunningMode.VIDEO if self._config["running_mode"] == "video" else vision.RunningMode.IMAGE
        )
        options = vision.HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=model, delegate=BaseOptions.Delegate.CPU),
            running_mode=mode,
            num_hands=int(self._config["num_hands"]),
            min_hand_detection_confidence=float(self._config["min_hand_detection_confidence"]),
            min_hand_presence_confidence=float(self._config["min_hand_presence_confidence"]),
            min_tracking_confidence=float(self._config["min_tracking_confidence"]),
        )
        self._landmarker = vision.HandLandmarker.create_from_options(options)
        self._last_ms = -1

    def reset(self, video: VideoContext | None = None) -> None:
        # VIDEO mode keeps state keyed on timestamps; a fresh landmarker is the only clean reset.
        if self._landmarker is not None:
            self.close()
            self.load(self._given)

    def close(self) -> None:
        if self._landmarker is not None:
            self._landmarker.close()
            self._landmarker = None

    def metadata(self) -> AdapterMetadata:
        return AdapterMetadata(
            name="mediapipe-hands",
            version=f"hand_landmarker@{HAND_LANDMARKER.sha256[:8]} mediapipe-{package_version('mediapipe')}",
            keypoint_schema=keypoints.SCHEMA,
        )

    def predict(self, frames: Sequence[Frame]) -> list[HandResult]:
        if self._landmarker is None:
            raise AdapterError("adapter not loaded")
        import mediapipe as mp

        out: list[HandResult] = []
        for frame in frames:
            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(frame.image))
            if self._config["running_mode"] == "video":
                # Timestamps must strictly increase; frames can be closer than 1 ms in real files.
                ms = max(self._last_ms + 1, int(round(frame.timestamp_s * 1000)))
                self._last_ms = ms
                result = self._landmarker.detect_for_video(image, ms)
            else:
                result = self._landmarker.detect(image)
            hands = []
            for lms, handed in zip(result.hand_landmarks, result.handedness, strict=True):
                label = handed[0].category_name.lower()
                if self._config["mirrored_input"]:
                    label = "left" if label == "right" else "right"
                score = float(handed[0].score)
                hands.append(
                    HandDetection(
                        handedness=label,  # type: ignore[arg-type]
                        handedness_score=score,
                        # HandLandmarker drops hands below the presence threshold but doesn't report the
                        # presence score itself; the handedness score is the confidence it does report.
                        confidence=score,
                        keypoints=np.array([[p.x, p.y, p.z] for p in lms], dtype=np.float32),
                    )
                )
            out.append(HandResult(frame_index=frame.index, timestamp_s=frame.timestamp_s, hands=hands))
        return out
