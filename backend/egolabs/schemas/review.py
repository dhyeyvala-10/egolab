"""Review, active learning, auto-accept rules, bulk review, metrics, and auto annotation (spec Phase 5)."""

import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

from egolabs.models.enums import CvRunKind, MovementEventStatus, ReviewMethod
from egolabs.schemas import ApiModel
from egolabs.schemas.annotation import UserRef
from egolabs.schemas.catalog import Ref
from egolabs.schemas.cv import CvRunSummary
from egolabs.schemas.movement import ClassRef, MovementEventDetail, MovementEventSummary

Finger = Literal["thumb", "index", "middle", "ring", "pinky"]


class ReviewFilters(BaseModel):
    """What a queue, summary, or bulk review covers. Empty fields don't filter."""

    video_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    classes: list[str] = Field(default_factory=list, max_length=50, description="Class names")
    object_label: Annotated[str, StringConstraints(max_length=100)] | None = None
    no_object: bool = Field(default=False, description="Only events with no object")
    handedness: Literal["left", "right"] | None = None
    statuses: list[MovementEventStatus] = Field(
        default_factory=lambda: [MovementEventStatus.auto_detected, MovementEventStatus.needs_review],
        description="Default: pending (auto_detected, needs_review)",
    )
    min_confidence: float | None = Field(default=None, ge=0, le=1)
    max_confidence: float | None = Field(default=None, ge=0, le=1)
    event_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500, description="Selected events")


class PriorityParts(BaseModel):
    """Why an item is where it is in the queue: each weighted term of its priority."""

    confidence: float = Field(description="w_c × (1 − confidence)")
    disagreement: float = Field(description="w_d × disagreement (0 when unknown)")
    rarity: float = Field(description="w_r × class rarity")


class ReviewItem(MovementEventSummary):
    disagreement: float | None = Field(
        description="1 − agreement with other model versions; None: not compared"
    )
    compared_versions: int
    rarity: float = Field(description="1 for the rarest class, 0 for the most common")
    priority: float
    priority_parts: PriorityParts


class QueuePage(BaseModel):
    items: list[ReviewItem]
    total: int
    limit: int
    offset: int
    weights: dict[str, float]


class ReviewGroup(BaseModel):
    """One card on the review home: a class, or an object."""

    key: str = Field(description="Class name, or object label ('' for events with no object)")
    label: str
    movement_class: ClassRef | None
    total: int
    pending: int
    needs_review: int
    confirmed: int
    auto_accepted: int = Field(description="Of the confirmed, how many an auto-accept rule confirmed")
    rejected: int
    corrected: int
    mean_confidence: float | None
    min_confidence: float | None


class ReviewSummary(BaseModel):
    group: Literal["class", "object"]
    groups: list[ReviewGroup]
    totals: ReviewGroup


class ReviewStatusUpdate(BaseModel):
    status: Literal["auto_detected", "needs_review", "confirmed", "rejected"]


class CorrectionCreate(BaseModel):
    """The corrected fields; omitted fields keep the prediction's value."""

    class_name: Annotated[str, StringConstraints(max_length=64)] | None = Field(default=None, alias="class")
    start_frame: int | None = Field(default=None, ge=0)
    end_frame: int | None = Field(default=None, ge=0)
    handedness: Literal["left", "right"] | None = None
    fingers: list[Finger] | None = None
    object_label: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)] | None
    ) = None
    clear_object: bool = Field(default=False, description="The event involves no object")

    model_config = {"populate_by_name": True}


class ReviewLogEntry(ApiModel):
    id: uuid.UUID
    event_id: uuid.UUID
    from_status: MovementEventStatus | None
    to_status: MovementEventStatus
    method: ReviewMethod
    actor: UserRef | None
    batch_id: uuid.UUID | None
    rule_id: uuid.UUID | None
    related_event_id: uuid.UUID | None
    created_at: datetime


class EventVersion(BaseModel):
    id: uuid.UUID
    source: str = Field(description="auto (the prediction) or auto_corrected (a person's correction)")
    movement_class: ClassRef
    start_frame: int
    end_frame: int
    handedness: str
    fingers: list[str]
    object_label: str | None
    confidence: float | None
    status: MovementEventStatus
    superseded_at: datetime | None
    created_at: datetime
    annotation_id: uuid.UUID


class EventHistory(BaseModel):
    """An event's versions, oldest first (the prediction, then its corrections), and its review log."""

    versions: list[EventVersion]
    log: list[ReviewLogEntry]


class CorrectionResult(BaseModel):
    event: MovementEventDetail = Field(description="The event that now holds the correction")
    parent_event_id: uuid.UUID | None


class BulkRequest(BaseModel):
    filters: ReviewFilters
    action: Literal["confirmed", "rejected"]


class BulkPreview(BaseModel):
    count: int
    limit: int
    over_limit: bool
    sample: list[MovementEventSummary] = Field(description="The first few events it would change")
    by_class: dict[str, int]


class ReviewBatchRead(ApiModel):
    id: uuid.UUID
    action: MovementEventStatus
    method: ReviewMethod
    filters: dict[str, Any]
    count: int
    actor: UserRef | None
    created_at: datetime
    undone_at: datetime | None
    undone_by: UserRef | None
    undone_count: int


class RuleApplyRequest(BaseModel):
    filters: ReviewFilters = Field(default_factory=ReviewFilters)


class ReviewRuleRead(ApiModel):
    id: uuid.UUID
    movement_class: ClassRef | None = Field(description="None: the default for classes without a rule")
    min_confidence: float
    enabled: bool
    created_at: datetime
    updated_at: datetime | None
    accepted: int = Field(description="Events this rule has confirmed")


class ReviewRuleCreate(BaseModel):
    class_name: Annotated[str, StringConstraints(max_length=64)] | None = Field(
        default=None, alias="class", description="None: the default rule"
    )
    min_confidence: float = Field(ge=0, le=1)
    enabled: bool = True

    model_config = {"populate_by_name": True}


class ReviewRuleUpdate(BaseModel):
    min_confidence: float | None = Field(default=None, ge=0, le=1)
    enabled: bool | None = None


class ClassMetric(BaseModel):
    movement_class: ClassRef
    predictions: int
    pending: int
    auto_accepted: int
    human_reviewed: int = Field(description="Predictions a person confirmed, corrected, or rejected")
    confirmed: int
    corrected: int
    rejected: int
    accuracy: float | None = Field(description="confirmed / human_reviewed: agreement with human review")


class AnnotatorMetric(BaseModel):
    user: UserRef
    reviews: int = Field(description="Every status change this person made in the window (undos excluded)")
    individual: int
    bulk: int
    corrections: int
    inspector: int
    confirmed: int
    rejected: int
    flagged: int
    active_hours: int = Field(description="Distinct clock hours with at least one review")
    per_hour: float | None = Field(description="Individual reviews and corrections per active hour")
    first_at: datetime
    last_at: datetime


class DailyReviews(BaseModel):
    day: date
    human: int
    auto_rule: int


class ReviewMetrics(BaseModel):
    days: int
    since: datetime
    predictions: int = Field(description="Predictions in each video's latest classification run")
    pending: int
    auto_accepted: int
    human_reviewed: int
    confirmed: int
    corrected: int
    rejected: int
    correction_rate: float | None = Field(description="corrected / human_reviewed")
    rejection_rate: float | None
    per_class: list[ClassMetric]
    annotators: list[AnnotatorMetric]
    daily: list[DailyReviews]


class ModelChoice(BaseModel):
    """A registered model version, or an adapter and config (a new setup registers a new version)."""

    model_version_id: uuid.UUID | None = None
    adapter: Annotated[str, StringConstraints(min_length=1, max_length=300)] | None = None
    config: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _one(self) -> "ModelChoice":
        if (self.model_version_id is None) == (self.adapter is None):
            raise ValueError("give either model_version_id or adapter")
        return self


class AutoAnnotateRequest(BaseModel):
    session_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    video_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    kinds: list[CvRunKind] | None = Field(default=None, min_length=1, description="Default: CV_DEFAULT_KINDS")
    models: dict[CvRunKind, ModelChoice] = Field(
        default_factory=dict, description="Per kind; kinds left out use the configured adapter"
    )
    stride: int = Field(default=1, ge=1, le=30)

    @model_validator(mode="after")
    def _some(self) -> "AutoAnnotateRequest":
        if not self.session_ids and not self.video_ids:
            raise ValueError("choose at least one session or video")
        return self


class SkippedVideo(BaseModel):
    video: Ref
    reason: str


class AutoAnnotateResult(BaseModel):
    videos: int
    runs: list[CvRunSummary]
    skipped: list[SkippedVideo]
    setups: dict[str, dict[str, Any]] = Field(
        description="Per kind: the adapter and config each run was given"
    )


class ModelVersionRead(ApiModel):
    id: uuid.UUID
    name: str
    version: str
    kind: str
    adapter: str
    config: dict[str, Any]
    created_at: datetime
    runs: int
    last_run_at: datetime | None
    configured: bool = Field(description="The setup the settings choose now")
