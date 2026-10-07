"""MediaPipe ObjectDetector with EfficientDet-Lite0 (COCO labels), on CPU."""

from collections.abc import Sequence
from importlib.metadata import version as package_version
from typing import Any

import numpy as np

from egolabs.cv.adapters.base import (
    AdapterError,
    AdapterMetadata,
    Frame,
    ObjectDetection,
    ObjectDetectionAdapter,
    ObjectResult,
    VideoContext,
)
from egolabs.cv.assets import EFFICIENTDET_LITE0, ensure

# The 80 COCO labels EfficientDet-Lite0 outputs.
COCO_LABELS = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat", "traffic light",
    "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow",
    "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
    "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove", "skateboard", "surfboard",
    "tennis racket", "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
    "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
    "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote", "keyboard",
    "cell phone", "microwave", "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase", "scissors",
    "teddy bear", "hair drier", "toothbrush",
]  # fmt: skip

DEFAULTS: dict[str, Any] = {
    "score_threshold": 0.4,
    "max_results": 10,
    # In egocentric footage the camera wearer's own hands and arms come back as "person"; the hand tracker
    # already covers them, so they are left out by default.
    "category_denylist": ["person"],
    "category_allowlist": None,  # e.g. ["cup", "bottle"] to keep only those
    "running_mode": "video",
    "model_path": None,  # default: the pinned efficientdet_lite0.tflite, downloaded and checksummed on first use
}


class MediaPipeObjects(ObjectDetectionAdapter):
    labels = COCO_LABELS

    def __init__(self) -> None:
        self._detector: Any = None
        self._given: dict[str, Any] = {}
        self._config: dict[str, Any] = {}
        self._last_ms = -1

    def load(self, config: dict[str, Any]) -> None:
        unknown = set(config) - set(DEFAULTS)
        if unknown:
            raise AdapterError(f"unknown mediapipe-objects options: {', '.join(sorted(unknown))}")
        self._given = dict(config)
        self._config = {**DEFAULTS, **config}
        if self._config["running_mode"] not in ("video", "image"):
            raise AdapterError("running_mode must be 'video' or 'image'")
        if (
            self._config["category_allowlist"]
            and self._config["category_denylist"]
            and "category_denylist" in config
        ):
            raise AdapterError("set category_allowlist or category_denylist, not both")
        try:
            from mediapipe.tasks.python import BaseOptions, vision
        except ImportError as exc:  # pragma: no cover - dependency is required in the image
            raise AdapterError("mediapipe is not installed") from exc
        model = self._config["model_path"] or str(ensure(EFFICIENTDET_LITE0))
        mode = (
            vision.RunningMode.VIDEO if self._config["running_mode"] == "video" else vision.RunningMode.IMAGE
        )
        allow = self._config["category_allowlist"]
        options = vision.ObjectDetectorOptions(
            base_options=BaseOptions(model_asset_path=model, delegate=BaseOptions.Delegate.CPU),
            running_mode=mode,
            score_threshold=float(self._config["score_threshold"]),
            max_results=int(self._config["max_results"]),
            # MediaPipe accepts one of the two lists.
            category_allowlist=list(allow) if allow else None,
            category_denylist=None if allow else list(self._config["category_denylist"] or []),
        )
        self._detector = vision.ObjectDetector.create_from_options(options)
        self._last_ms = -1

    def reset(self, video: VideoContext | None = None) -> None:
        if self._detector is not None:
            self.close()
            self.load(self._given)

    def close(self) -> None:
        if self._detector is not None:
            self._detector.close()
            self._detector = None

    def metadata(self) -> AdapterMetadata:
        return AdapterMetadata(
            name="mediapipe-objects",
            version=f"efficientdet_lite0@{EFFICIENTDET_LITE0.sha256[:8]} mediapipe-{package_version('mediapipe')}",
            labels=COCO_LABELS,
        )

    def predict(self, frames: Sequence[Frame]) -> list[ObjectResult]:
        if self._detector is None:
            raise AdapterError("adapter not loaded")
        import mediapipe as mp

        out: list[ObjectResult] = []
        for frame in frames:
            h, w = frame.image.shape[:2]
            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(frame.image))
            if self._config["running_mode"] == "video":
                ms = max(self._last_ms + 1, int(round(frame.timestamp_s * 1000)))
                self._last_ms = ms
                result = self._detector.detect_for_video(image, ms)
            else:
                result = self._detector.detect(image)
            objects = []
            for d in result.detections:
                cat = d.categories[0]
                b = d.bounding_box  # pixels of the image it saw
                x0, y0 = max(0.0, b.origin_x / w), max(0.0, b.origin_y / h)
                x1, y1 = min(1.0, (b.origin_x + b.width) / w), min(1.0, (b.origin_y + b.height) / h)
                if x1 <= x0 or y1 <= y0:
                    continue
                objects.append(ObjectDetection(label=cat.category_name, score=float(cat.score),
                                               bbox=(x0, y0, x1 - x0, y1 - y0)))  # fmt: skip
            out.append(ObjectResult(frame_index=frame.index, timestamp_s=frame.timestamp_s, objects=objects))
        return out
