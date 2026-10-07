"""
Which model runs is configuration, per kind of model (principle 10):

| kind               | adapter setting              | config setting               |
| ------------------ | ---------------------------- | ---------------------------- |
| `hand_tracking`    | `HAND_TRACKING_ADAPTER`      | `HAND_TRACKING_CONFIG`       |
| `object_detection` | `OBJECT_DETECTION_ADAPTER`   | `OBJECT_DETECTION_CONFIG`    |
| `movement`         | `MOVEMENT_CLASSIFIER_ADAPTER`| `MOVEMENT_CLASSIFIER_CONFIG` |

The adapter setting names one of the adapters below or gives an import path `package.module:Class`; the
config is its JSON config. The API, workers, and UI only ever see an adapter's output and metadata.
"""

import hashlib
import importlib
import json
from dataclasses import dataclass
from typing import Any

from egolabs.config import get_settings
from egolabs.cv.adapters.base import AdapterError, HandTrackingAdapter, ObjectDetectionAdapter
from egolabs.cv.movement.base import MovementClassifier


@dataclass(frozen=True)
class Kind:
    base: type
    setting: str  # settings attribute prefix: <setting>_adapter, <setting>_config
    adapters: dict[str, str]

    @property
    def env(self) -> tuple[str, str]:
        return f"{self.setting.upper()}_ADAPTER", f"{self.setting.upper()}_CONFIG"


KINDS: dict[str, Kind] = {
    "hand_tracking": Kind(HandTrackingAdapter, "hand_tracking", {
        "mediapipe-hands": "egolabs.cv.adapters.mediapipe_hands:MediaPipeHands",
        "keypoint-file": "egolabs.cv.adapters.keypoint_file:KeypointFileAdapter",
        # Documented stubs (see egolabs.cv.adapters.stubs); selecting one fails with what it needs.
        "rtmpose-hands": "egolabs.cv.adapters.stubs:RTMPoseHands",
        "yolo-pose-hands": "egolabs.cv.adapters.stubs:YoloPoseHands",
        "torchscript-hands": "egolabs.cv.adapters.stubs:TorchScriptHands",
        "tensorflow-hands": "egolabs.cv.adapters.stubs:TensorFlowHands",
    }),
    "object_detection": Kind(ObjectDetectionAdapter, "object_detection", {
        "mediapipe-objects": "egolabs.cv.adapters.mediapipe_objects:MediaPipeObjects",
        "detections-file": "egolabs.cv.adapters.detections_file:DetectionsFileAdapter",
        "yolo-objects": "egolabs.cv.adapters.stubs:YoloObjects",
    }),
    "movement": Kind(MovementClassifier, "movement_classifier", {
        "rules": "egolabs.cv.movement.rules:RuleClassifier",
        "events-file": "egolabs.cv.movement.events_file:EventsFileClassifier",
    }),
}  # fmt: skip

# Hand-tracking adapters (the Phase 3 name, kept for callers that only deal with hands).
ADAPTERS = KINDS["hand_tracking"].adapters


def _kind(kind: str) -> Kind:
    try:
        return KINDS[kind]
    except KeyError:
        raise AdapterError(f"unknown model kind {kind!r}; one of {', '.join(KINDS)}") from None


def configured(kind: str = "hand_tracking") -> tuple[str, dict[str, Any]]:
    settings, k = get_settings(), _kind(kind)
    return getattr(settings, f"{k.setting}_adapter"), dict(getattr(settings, f"{k.setting}_config"))


def target(name: str, kind: str = "hand_tracking") -> str:
    """The import path a configured adapter name stands for."""
    return _kind(kind).adapters.get(name, name)


def name_for(adapter_target: str, kind: str = "hand_tracking") -> str:
    """The registry name for an adapter import path (a model version's `adapter`), else the path itself."""
    return next((n for n, t in _kind(kind).adapters.items() if t == adapter_target), adapter_target)


def resolve(name: str, kind: str = "hand_tracking") -> type:
    k = _kind(kind)
    path = target(name, kind)
    module_name, _, attr = path.partition(":")
    if not attr:
        raise AdapterError(
            f"unknown adapter {name!r}; use one of {', '.join(k.adapters)} or 'package.module:Class'"
        )
    try:
        cls = getattr(importlib.import_module(module_name), attr)
    except (ImportError, AttributeError) as exc:
        raise AdapterError(f"can't import adapter {path}: {exc}") from exc
    if not (isinstance(cls, type) and issubclass(cls, k.base)):
        raise AdapterError(f"{path} is not a {k.base.__name__}")
    return cls


def is_stub(cls: type) -> bool:
    return bool(getattr(cls, "stub", False))


def create(name: str, config: dict[str, Any], kind: str = "hand_tracking") -> Any:
    adapter = resolve(name, kind)()
    adapter.load(config)
    return adapter


def config_hash(name: str, config: dict[str, Any], kind: str = "hand_tracking") -> str:
    """Short stable hash of an adapter and its config, so each distinct setup is its own model version."""
    blob = json.dumps({"adapter": target(name, kind), "config": config}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:8]
