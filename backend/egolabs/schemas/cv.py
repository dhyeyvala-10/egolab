"""Model runs: hand and finger tracking (spec Phase 3), object detection and movement classification (Phase 4)."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from egolabs.models.enums import CvRunKind, CvRunStatus
from egolabs.schemas import ApiModel
from egolabs.schemas.catalog import Ref


class ModelVersionRead(ApiModel):
    id: uuid.UUID
    name: str
    version: str
    kind: str
    adapter: str
    config: dict[str, Any]
    keypoint_schema: dict[str, Any] | None
    created_at: datetime


class ModelVersionRef(ApiModel):
    id: uuid.UUID
    name: str
    version: str


class AdapterInfo(BaseModel):
    kind: CvRunKind
    env: tuple[str, str] = Field(description="The settings that choose it: (adapter, JSON config)")
    name: str = Field(description="The configured adapter: a registry name or an import path")
    target: str = Field(description="The adapter class it resolves to")
    config: dict[str, Any] = Field(description="Its JSON config")
    runnable: bool = Field(description="False for the documented stubs")
    error: str | None = Field(description="Why the configured adapter can't be used, if it can't")
    registered: list[str] = Field(description="Adapter names available to configure")
    stubs: list[str] = Field(description="Registered names that are documented stubs")
    detects: list[str] | None = Field(
        description="Labels an object detector outputs, or classes a movement classifier emits, if fixed"
    )
    model_version: ModelVersionRef | None = Field(
        description="Model version of the latest run with this setup"
    )


class CvRunCreate(BaseModel):
    video_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    stride: int = Field(default=1, ge=1, le=30, description="Process every Nth frame")
    kinds: list[CvRunKind] | None = Field(
        default=None,
        min_length=1,
        description="What to run (default: CV_DEFAULT_KINDS — hand tracking, object detection, and movement "
        "classification on their output). Movement alone re-classifies the latest successful runs.",
    )


class CvRunSummary(BaseModel):
    id: uuid.UUID
    video: Ref
    kind: str
    status: CvRunStatus
    adapter: str
    model_version: ModelVersionRef | None
    stride: int
    frames_total: int | None
    frames_processed: int
    frames_with_hands: int
    detections: int
    tracks: int
    missing_detections: int = Field(description="Frames inside a track's life with no detection")
    tracking_failures: int = Field(description="Hands dropped and picked up again under a new track ID")
    mean_confidence: float | None
    inputs: dict[str, uuid.UUID] = Field(description="Runs this one reads, by kind")
    error: str | None
    job_id: uuid.UUID | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class HandTrackRead(ApiModel):
    track_id: int
    handedness: str
    first_frame: int
    last_frame: int
    frames_detected: int
    missing_detections: int
    mean_confidence: float
    path_length_px: float
    mean_speed_px_s: float
    peak_speed_px_s: float
    model_version_id: uuid.UUID


class ObjectTrackRead(ApiModel):
    track_id: int
    label: str
    first_frame: int
    last_frame: int
    frames_detected: int
    missing_detections: int
    mean_score: float
    max_score: float
    mean_bbox: list[float]
    path_length_px: float
    model_version_id: uuid.UUID


class CvRunDetail(CvRunSummary):
    config: dict[str, Any]
    stats: dict[str, Any]
    output_rows: dict[str, int]
    hand_tracks: list[HandTrackRead]
    object_tracks: list[ObjectTrackRead]


class FingerState(BaseModel):
    finger: str
    visibility: float
    occluded: bool


class HandInFrame(BaseModel):
    track_id: int
    handedness: str
    confidence: float
    bbox: tuple[float, float, float, float]
    keypoints: list[tuple[float, float]] = Field(description="21 smoothed keypoints, normalised to the frame")
    fingers: list[FingerState]


class FrameHands(BaseModel):
    frame: int
    timestamp_s: float
    hands: list[HandInFrame]


class RunFrames(BaseModel):
    run_id: uuid.UUID
    model_version_id: uuid.UUID | None
    frame_from: int
    frame_to: int
    frames: list[FrameHands] = Field(description="Only frames with at least one hand")


SeriesMetric = Literal["speed", "accel", "visibility"]


class SeriesPoint(BaseModel):
    frame_start: int
    frame_end: int
    t: float = Field(description="Seconds at the bucket's first sample")
    mean: float
    min: float
    max: float
    n: int


class Series(BaseModel):
    name: str = Field(description="wrist, thumb, index, middle, ring, or pinky")
    points: list[SeriesPoint]


class RunSeries(BaseModel):
    run_id: uuid.UUID
    track_id: int
    metric: SeriesMetric
    unit: str
    frame_from: int
    frame_to: int
    series: list[Series]


class ObjectInFrame(BaseModel):
    track_id: int
    label: str
    score: float
    bbox: tuple[float, float, float, float] = Field(description="x, y, w, h normalised to the frame")


class FrameObjects(BaseModel):
    frame: int
    timestamp_s: float
    objects: list[ObjectInFrame]


class RunObjects(BaseModel):
    run_id: uuid.UUID
    model_version_id: uuid.UUID | None
    frame_from: int
    frame_to: int
    frames: list[FrameObjects] = Field(description="Only frames with at least one object")
