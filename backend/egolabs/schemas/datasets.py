"""Dataset versions, their samples, rebuild checks, exports, and lineage (spec Phase 6)."""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

from egolabs.models.enums import BuildStatus, ExportFormat, SplitGroup
from egolabs.schemas import ApiModel
from egolabs.schemas.annotation import UserRef
from egolabs.schemas.catalog import Ref
from egolabs.schemas.cv import ModelVersionRef

Short = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
EventStatus = Literal["auto_detected", "needs_review", "confirmed", "rejected"]


class DatasetFilters(BaseModel):
    """Which samples a version takes. Empty lists don't filter."""

    # Videos (resolved when the version is created, and pinned in its inputs)
    session_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    device_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)
    environments: list[Short] = Field(default_factory=list, max_length=100)
    video_ids: list[uuid.UUID] = Field(default_factory=list, max_length=5000)
    exclude_quality_flags: list[Annotated[str, StringConstraints(max_length=32)]] = Field(
        default_factory=list, description="Leave out videos with any of these flags"
    )
    # Samples (evaluated as the data stood at the version's as_of)
    classes: list[Annotated[str, StringConstraints(max_length=64)]] = Field(
        default_factory=list, max_length=100
    )
    statuses: list[EventStatus] = Field(default_factory=lambda: ["confirmed"], min_length=1,
                                        description="Review statuses to include (default: confirmed only)")  # fmt: skip
    human_verified_only: bool = Field(
        default=False,
        description="Confirmed only by a person (review, bulk review, or correction), not auto-accept",
    )
    min_confidence: float | None = Field(default=None, ge=0, le=1, description="Applies to predictions")
    max_confidence: float | None = Field(default=None, ge=0, le=1)
    handedness: list[Literal["left", "right"]] = Field(default_factory=list)
    object_labels: list[Short] = Field(default_factory=list, max_length=100)
    require_object: bool | None = Field(
        default=None, description="True: only with an object; false: only without"
    )


class SplitSpec(BaseModel):
    train: float = Field(default=0.8, ge=0, le=1)
    val: float = Field(default=0.1, ge=0, le=1)
    test: float = Field(default=0.1, ge=0, le=1)
    group_by: SplitGroup = Field(
        default=SplitGroup.session,
        description="Kept together in one split, so a scene or a person never appears in two",
    )
    seed: int = Field(default=0, ge=0, le=2**31 - 1)

    @model_validator(mode="after")
    def _sums_to_one(self) -> "SplitSpec":
        if abs(self.train + self.val + self.test - 1.0) > 1e-6:
            raise ValueError("train + val + test must add up to 1")
        return self


class DatasetSpec(BaseModel):
    filters: DatasetFilters = Field(default_factory=DatasetFilters)
    split: SplitSpec = Field(default_factory=SplitSpec)


class VersionCreate(BaseModel):
    spec: DatasetSpec = Field(default_factory=DatasetSpec)
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None = None


class SplitCounts(BaseModel):
    train: int = 0
    val: int = 0
    test: int = 0


class VersionCounts(BaseModel):
    splits: SplitCounts = Field(default_factory=SplitCounts)
    groups: SplitCounts = Field(default_factory=SplitCounts, description="Distinct groups per split")
    classes: dict[str, SplitCounts] = Field(default_factory=dict)
    statuses: dict[str, int] = Field(default_factory=dict)
    sources: dict[str, int] = Field(default_factory=dict)
    videos: int = 0


class PreviewSample(BaseModel):
    annotation_id: uuid.UUID
    event_id: uuid.UUID
    video_id: uuid.UUID
    class_name: str
    start_frame: int
    end_frame: int
    status: str
    source: str
    confidence: float | None
    split: str


class DatasetPreview(BaseModel):
    videos: int
    runs: int
    sample_count: int
    truncated: bool = Field(description="Stopped counting at the preview limit")
    counts: VersionCounts
    sample: list[PreviewSample]
    warnings: list[str]


class DatasetDetail(ApiModel):
    id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime
    sessions: list[Ref]
    versions: int
    latest_version: int | None


class VersionSummary(BaseModel):
    id: uuid.UUID
    dataset: Ref
    number: int
    status: BuildStatus
    parent_version_id: uuid.UUID | None
    content_hash: str | None
    sample_count: int
    counts: VersionCounts
    created_at: datetime
    built_at: datetime | None
    created_by: UserRef | None
    error: str | None
    note: str | None


class VersionDetail(VersionSummary):
    spec: DatasetSpec
    inputs: dict[str, Any] = Field(
        description="as_of, the pinned videos (with session and operator), and runs"
    )
    model_versions: list[ModelVersionRef]
    job_id: uuid.UUID | None


class SampleRead(ApiModel):
    id: uuid.UUID
    version_id: uuid.UUID
    sample_no: int
    split: str
    group_key: str
    annotation_id: uuid.UUID
    annotation_revision: int
    event_id: uuid.UUID
    video_id: uuid.UUID
    session_id: uuid.UUID | None
    class_name: str
    label: str
    start_frame: int
    end_frame: int
    start_s: float
    end_s: float
    handedness: str
    hand_track_id: int
    fingers: list[str]
    object_label: str | None
    object_track_id: int | None
    source: str
    status: str
    review_method: str | None
    confidence: float | None
    model_version_id: uuid.UUID
    run_id: uuid.UUID
    hand_run_id: uuid.UUID
    object_run_id: uuid.UUID | None


class CheckRead(ApiModel):
    id: uuid.UUID
    version_id: uuid.UUID
    status: BuildStatus
    content_hash: str | None
    sample_count: int | None
    matches: bool | None
    created_at: datetime
    finished_at: datetime | None
    error: str | None
    job_id: uuid.UUID | None


class ExportCreate(BaseModel):
    format: ExportFormat


class ExportRead(BaseModel):
    id: uuid.UUID
    version_id: uuid.UUID
    dataset: Ref
    version_number: int
    format: ExportFormat
    status: BuildStatus
    size_bytes: int | None
    sha256: str | None
    files: int | None
    created_at: datetime
    finished_at: datetime | None
    error: str | None
    job_id: uuid.UUID | None


class ExportDownload(BaseModel):
    url: str
    filename: str
    expires_s: int


class QualityFlagInfo(BaseModel):
    flag: str
    description: str
    videos: int


class DatasetFacets(BaseModel):
    environments: list[str]
    object_labels: list[str]
    quality_flags: list[QualityFlagInfo]
    formats: list[ExportFormat]


class LineageNode(BaseModel):
    id: str = Field(description="type:uuid, or type:… for nodes without their own row (raw file, frames)")
    type: Literal["sample", "dataset_version", "dataset", "annotation", "event", "cv_run", "model_version", "job",
                  "video", "upload", "raw_file", "frames", "session"]  # fmt: skip
    label: str
    detail: dict[str, Any] = Field(default_factory=dict)
    href: str | None = Field(description="The page for this node in the web app")


class LineageEdgeRead(BaseModel):
    source: str
    target: str
    relation: str


class LineageGraph(BaseModel):
    root: str
    nodes: list[LineageNode]
    edges: list[LineageEdgeRead]
    reaches_raw_file: bool
