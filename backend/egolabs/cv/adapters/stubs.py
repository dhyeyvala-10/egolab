"""
Documented starting points for other models. A hand model maps its output onto the hand-21 schema
(`egolabs.cv.keypoints`) and returns `HandResult`s; an object detector returns `ObjectResult`s. Nothing else
in Ego Labs changes. Register a finished adapter in `egolabs.cv.registry` (or point `HAND_TRACKING_ADAPTER`
/ `OBJECT_DETECTION_ADAPTER` at its import path).

These are not runnable yet (`stub = True`): `load` raises with what's needed.
"""

from collections.abc import Sequence
from typing import Any

from egolabs.cv import keypoints
from egolabs.cv.adapters.base import (
    AdapterError,
    AdapterMetadata,
    Frame,
    HandResult,
    HandTrackingAdapter,
    ObjectDetectionAdapter,
    ObjectResult,
)


class _Stub(HandTrackingAdapter):
    NAME = ""
    NEEDS = ""
    stub = True

    def load(self, config: dict[str, Any]) -> None:
        raise AdapterError(f"{self.NAME} is a documented stub, not an implementation yet. {self.NEEDS}")

    def predict(self, frames: Sequence[Frame]) -> list[HandResult]:
        raise AdapterError(f"{self.NAME} is not implemented")

    def metadata(self) -> AdapterMetadata:
        return AdapterMetadata(name=self.NAME, version="stub", keypoint_schema=keypoints.SCHEMA)


class RTMPoseHands(_Stub):
    """
    RTMPose (MMPose) hand model, e.g. `rtmpose-m_simcc-hand5`.

    - Detector: RTMDet-nano hand detector → person/hand boxes; RTMPose top-down on each box.
    - Output: 21 keypoints in the COCO-WholeBody hand order, which matches hand-21 (wrist, thumb 1–4, …).
      Normalise pixel coordinates by frame width/height; z = 0 (2-D model).
    - Confidence: mean keypoint score; `keypoint_confidence` = the per-keypoint scores.
    - Handedness: RTMPose has none — take it from the detector if it has classes, else from the thumb side
      relative to the palm normal.
    - Config: `{"pose_config", "pose_checkpoint", "det_config", "det_checkpoint", "device"}`.
    """

    NAME = "rtmpose-hands"
    NEEDS = "Install mmpose/mmdet and implement predict() as described in the class docstring."


class YoloPoseHands(_Stub):
    """
    Ultralytics YOLO pose model trained on a 21-keypoint hand dataset (e.g. `hand-keypoints`).

    - `model(frame.image, verbose=False)`; each result's `boxes.conf` → confidence, `keypoints.xyn` → x, y
      (already normalised), `keypoints.conf` → keypoint_confidence.
    - Handedness: train with two classes (left/right hand) and read `boxes.cls`.
    - Config: `{"weights", "imgsz", "conf", "device"}`.
    """

    NAME = "yolo-pose-hands"
    NEEDS = "Install ultralytics, provide 21-keypoint hand weights, and implement predict()."


class TorchScriptHands(_Stub):
    """
    A custom PyTorch model exported with TorchScript.

    - Contract: input float32 N×3×H×W (RGB, 0–1); output `(keypoints N×H×21×3, scores N×H, handedness N×H)`
      for up to H hands per frame, keypoints normalised. Batch the `frames` passed to predict().
    - Config: `{"path", "device", "input_size", "max_hands"}`.
    """

    NAME = "torchscript-hands"
    NEEDS = "Install torch and implement predict() for your model's output contract."


class TensorFlowHands(_Stub):
    """
    A custom TensorFlow SavedModel (or TFLite file).

    - Same contract as TorchScriptHands, NHWC input. For TFLite use `tf.lite.Interpreter` and batch size 1.
    - Config: `{"path", "input_size", "max_hands"}`.
    """

    NAME = "tensorflow-hands"
    NEEDS = "Install tensorflow and implement predict() for your model's output contract."


class YoloObjects(ObjectDetectionAdapter):
    """
    Ultralytics YOLO detector (e.g. `yolo11n.pt`, COCO or custom classes).

    - `model.predict(frame.image, conf=…, verbose=False)`; for each box: `boxes.xyxyn` → normalised
      (x0, y0, x1, y1) → `bbox=(x0, y0, x1 - x0, y1 - y0)`, `boxes.conf` → score, `names[boxes.cls]` → label.
    - Batch the frames passed to predict(); `model.track(persist=True)` may replace Ego Labs' IoU tracker, but
      return plain detections — tracking IDs are assigned downstream.
    - Config: `{"weights", "imgsz", "conf", "device", "classes"}`.
    """

    NAME = "yolo-objects"
    NEEDS = (
        "Install ultralytics, provide weights, and implement predict() as described in the class docstring."
    )
    stub = True

    def load(self, config: dict[str, Any]) -> None:
        raise AdapterError(f"{self.NAME} is a documented stub, not an implementation yet. {self.NEEDS}")

    def predict(self, frames: Sequence[Frame]) -> list[ObjectResult]:
        raise AdapterError(f"{self.NAME} is not implemented")

    def metadata(self) -> AdapterMetadata:
        return AdapterMetadata(name=self.NAME, version="stub")
