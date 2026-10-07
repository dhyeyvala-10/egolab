"""Movement classes, movement events, and the interaction graph (spec Phase 4)."""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints

from egolabs.models.enums import MovementEventStatus
from egolabs.schemas import ApiModel
from egolabs.schemas.annotation import AnnotationRead, UserRef
from egolabs.schemas.catalog import Ref
from egolabs.schemas.cv import ModelVersionRef

ClassName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{1,63}$")]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]


class MovementClassRead(ApiModel):
    id: uuid.UUID
    name: str = Field(description="Stable identifier classifiers emit, e.g. pick_up")
    label: str
    description: str
    builtin: bool = Field(description="One of the spec's classes (can be relabelled or switched off)")
    active: bool = Field(description="Inactive classes are not recorded by new classification runs")
    requires_object: bool
    events: int = Field(description="Events of this class in each video's latest classification run")
    created_at: datetime
    updated_at: datetime | None


class MovementClassCreate(BaseModel):
    name: ClassName
    label: Label
    description: Description = ""
    requires_object: bool = False


class MovementClassUpdate(BaseModel):
    label: Label | None = None
    description: Description | None = None
    active: bool | None = None
    requires_object: bool | None = None


class ClassRef(BaseModel):
    id: uuid.UUID
    name: str
    label: str


class MovementEventSummary(BaseModel):
    id: uuid.UUID
    video: Ref
    session: Ref | None
    movement_class: ClassRef
    label: str = Field(description="As shown on the timeline, e.g. 'Swipe · left'")
    start_frame: int
    end_frame: int
    start_s: float
    end_s: float
    handedness: str
    hand_track_id: int
    fingers: list[str]
    object_track_id: int | None
    object_label: str | None
    confidence: float | None = Field(description="The model's; None for a person's correction")
    status: MovementEventStatus
    source: str = Field(description="auto: a prediction; auto_corrected: a person's correction of one")
    parent_event_id: uuid.UUID | None = Field(description="For a correction: the prediction it replaces")
    superseded_at: datetime | None = Field(description="Set when a correction replaced this prediction")
    review_method: str | None = Field(description="How the status was set: individual, bulk, auto_rule, …")
    model_version: ModelVersionRef
    run_id: uuid.UUID
    hand_run_id: uuid.UUID
    object_run_id: uuid.UUID | None
    annotation_id: uuid.UUID
    attributes: dict[str, Any]
    created_at: datetime


class EventEvidence(BaseModel):
    frames: list[int] = Field(description="The hand-tracking frames the event was derived from")
    frame_count: int
    measurements: dict[str, list[float]] = Field(
        description="Per evidence frame, the values the rule compared"
    )
    thresholds: dict[str, float]
    rule: str
    hand_run_id: uuid.UUID
    track_id: int
    parts: list[str] = Field(description="Parquet files of the hand-tracking run holding those frames")


class MovementEventDetail(MovementEventSummary):
    evidence: EventEvidence
    annotation: AnnotationRead
    reviewed_by: UserRef | None
    reviewed_at: datetime | None


class EvidenceFrame(BaseModel):
    frame: int
    timestamp_s: float
    confidence: float
    handedness: str
    keypoints: list[tuple[float, float]] = Field(description="21 smoothed keypoints, normalised to the frame")
    bbox: tuple[float, float, float, float]
    object_bbox: tuple[float, float, float, float] | None = Field(
        description="The event's object in this frame, if it has one and it was detected"
    )
    values: dict[str, float] = Field(description="This frame's measurements")


class EventEvidenceFrames(BaseModel):
    event_id: uuid.UUID
    hand_run_id: uuid.UUID
    model_version_id: uuid.UUID | None = Field(description="Model version of the hand-tracking run")
    track_id: int
    total: int
    offset: int
    limit: int
    frames: list[EvidenceFrame]


class MovementEventUpdate(BaseModel):
    status: Literal["auto_detected", "needs_review", "confirmed", "rejected"]


class GraphNode(BaseModel):
    id: str
    kind: Literal["hand", "finger", "movement", "object"]
    label: str
    count: int


class GraphLink(BaseModel):
    source: str
    target: str
    count: int


class GraphEvent(BaseModel):
    id: uuid.UUID
    video_id: uuid.UUID
    path: list[str] = Field(description="Node ids: hand, finger(s), movement, object")
    label: str
    start_frame: int
    end_frame: int
    start_s: float
    end_s: float
    confidence: float | None
    status: MovementEventStatus


class InteractionGraph(BaseModel):
    """Hand → Finger(s) → Movement → Object → Time range, over the events matching the filters."""

    nodes: list[GraphNode]
    links: list[GraphLink]
    events: list[GraphEvent] = Field(description="Each event's path and time range (at most `limit`)")
    total_events: int
