"""Annotations, their edit history, the inspector timeline, and the Annotation Queue."""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

from egolabs.models.enums import (
    AnnotationCategory,
    AnnotationSource,
    AnnotationType,
    AssignmentStatus,
    RevisionAction,
    Role,
)
from egolabs.schemas import ApiModel
from egolabs.schemas.catalog import Ref

Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Unit = Annotated[float, Field(ge=0, le=1)]


# --- geometry (normalised to the frame: 0–1, origin top left) --------------------------------------


class BoxData(BaseModel):
    box: tuple[Unit, Unit, Unit, Unit] = Field(description="[x, y, width, height], normalised to the frame")

    @model_validator(mode="after")
    def _inside_frame(self) -> "BoxData":
        x, y, w, h = self.box
        if w <= 0 or h <= 0:
            raise ValueError("box width and height must be positive")
        if x + w > 1 + 1e-9 or y + h > 1 + 1e-9:
            raise ValueError("box must lie inside the frame")
        return self


class Keypoint(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
    x: Unit
    y: Unit
    visible: bool = True


class KeypointData(BaseModel):
    points: list[Keypoint] = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def _unique_names(self) -> "KeypointData":
        names = [p.name for p in self.points]
        if len(set(names)) != len(names):
            raise ValueError("keypoint names must be unique")
        return self


def validate_data(kind: AnnotationType, data: dict[str, Any]) -> dict[str, Any]:
    """Check `data` against the annotation type and return it normalised."""
    if kind == AnnotationType.segment:
        if data:
            raise ValueError("segment annotations carry no geometry; leave data empty")
        return {}
    model = BoxData if kind == AnnotationType.bbox else KeypointData
    return model.model_validate(data).model_dump(mode="json")


# --- annotations -----------------------------------------------------------------------------------


class AnnotationCreate(BaseModel):
    type: AnnotationType
    label: Label
    category: AnnotationCategory = AnnotationCategory.general
    frame_start: int = Field(ge=0)
    frame_end: int = Field(ge=0, description="Inclusive")
    data: dict[str, Any] = Field(
        default_factory=dict, description="Box or keypoints; see BoxData/KeypointData"
    )
    needs_review: bool = False

    @model_validator(mode="after")
    def _check(self) -> "AnnotationCreate":
        if self.frame_end < self.frame_start:
            raise ValueError("frame_end must be at or after frame_start")
        self.data = validate_data(self.type, self.data)
        return self


class AnnotationUpdate(BaseModel):
    label: Label | None = None
    category: AnnotationCategory | None = None
    frame_start: int | None = Field(default=None, ge=0)
    frame_end: int | None = Field(default=None, ge=0)
    data: dict[str, Any] | None = None
    needs_review: bool | None = None
    revision: int | None = Field(
        default=None, description="The revision you edited; the update is refused if it has moved on"
    )


class UserRef(ApiModel):
    id: uuid.UUID
    name: str


class AnnotationRead(ApiModel):
    id: uuid.UUID
    video_id: uuid.UUID
    type: AnnotationType
    label: str
    category: AnnotationCategory
    frame_start: int
    frame_end: int
    data: dict[str, Any]
    source: AnnotationSource
    confidence: float | None
    model_version_id: uuid.UUID | None
    parent_annotation_id: uuid.UUID | None
    needs_review: bool
    revision: int
    author: UserRef | None
    created_at: datetime
    updated_at: datetime | None
    deleted_at: datetime | None
    superseded_at: datetime | None


class RevisionRead(ApiModel):
    revision: int
    action: RevisionAction
    changes: dict[str, Any]
    snapshot: dict[str, Any]
    actor: UserRef | None
    related_annotation_id: uuid.UUID | None
    created_at: datetime


class AnnotationHistory(BaseModel):
    annotation: AnnotationRead
    revisions: list[RevisionRead]
    parent: AnnotationRead | None = Field(description="The AI prediction this annotation corrects")
    corrections: list[AnnotationRead] = Field(description="Human corrections made from this annotation")


class LabelCount(BaseModel):
    label: str
    count: int


class AdjacentEvent(BaseModel):
    frame: int | None = Field(description="Start frame of the nearest annotation in that direction")
    annotation_id: uuid.UUID | None


# --- timeline --------------------------------------------------------------------------------------

TrackId = Literal["hand", "finger", "object", "movement", "ai", "human", "pipeline"]


class TimelineSegment(BaseModel):
    id: uuid.UUID
    start: int
    end: int
    label: str
    type: AnnotationType
    source: AnnotationSource
    confidence: float | None
    needs_review: bool


class TimelineBucket(BaseModel):
    start: int
    end: int
    count: int = Field(description="Annotations starting in this frame range")


class TimelineTrack(BaseModel):
    id: TrackId
    label: str
    kind: Literal["human", "ai", "event"]
    total: int = Field(description="Annotations on this track overlapping the requested range")
    segments: list[TimelineSegment] | None = Field(
        description="Every annotation in range, when there are few enough to draw"
    )
    buckets: list[TimelineBucket] | None = Field(
        description="Density per frame bucket, when there are too many"
    )
    filled_from_phase: int | None = Field(description="Build phase that starts producing this track's data")


class TimelineRead(BaseModel):
    frame_from: int
    frame_to: int
    tracks: list[TimelineTrack]


class FrameIndex(BaseModel):
    version: int
    frame_count: int
    time_base: tuple[int, int]
    runs: list[tuple[int, int, int]] = Field(
        description="[start_pts, step, count] runs in presentation order"
    )


class JobRef(BaseModel):
    job_id: uuid.UUID


# --- assignments -----------------------------------------------------------------------------------


class AssignableUser(ApiModel):
    id: uuid.UUID
    name: str
    email: str
    role: Role


class AssignmentCreate(BaseModel):
    session_id: uuid.UUID | None = None
    video_id: uuid.UUID | None = None
    assignee_id: uuid.UUID
    note: str | None = Field(default=None, max_length=5000)

    @model_validator(mode="after")
    def _one_target(self) -> "AssignmentCreate":
        if (self.session_id is None) == (self.video_id is None):
            raise ValueError("assign either a session or a video")
        return self


class AssignmentUpdate(BaseModel):
    status: AssignmentStatus | None = None
    assignee_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=5000)


class AssignmentProgress(BaseModel):
    videos: int
    annotated: int = Field(description="Videos with at least one human annotation")


class AssignmentRead(BaseModel):
    id: uuid.UUID
    target_type: Literal["session", "video"]
    session: Ref | None
    video: Ref | None
    assignee: UserRef
    assigned_by: UserRef | None
    status: AssignmentStatus
    note: str | None
    progress: AssignmentProgress
    created_at: datetime
    updated_at: datetime | None
    completed_at: datetime | None
