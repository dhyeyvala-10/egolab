import uuid
from datetime import date, datetime
from typing import Annotated, Any

from pydantic import AliasChoices, BaseModel, Field, StringConstraints

from egolabs.models.enums import UploadStatus, VideoSource, VideoStatus
from egolabs.schemas import ApiModel

Text200 = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
SESSION_NAME_PATTERN = r"^SESSION_\d{4}_\d{2}_\d{2}_\d{3}$"


# --- devices / operators ----------------------------------------------------------------------------


class DeviceCreate(BaseModel):
    name: Name
    kind: Text200 | None = None
    serial: Text200 | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DeviceUpdate(BaseModel):
    name: Name | None = None
    kind: Text200 | None = None
    serial: Text200 | None = None
    metadata: dict[str, Any] | None = None


class DeviceRead(ApiModel):
    id: uuid.UUID
    name: str
    kind: str | None
    serial: str | None
    metadata: dict[str, Any] = Field(validation_alias=AliasChoices("metadata_", "metadata"))
    created_at: datetime


class DeviceSummary(DeviceRead):
    session_count: int
    video_count: int


class OperatorCreate(BaseModel):
    name: Name
    external_id: Text200 | None = None
    notes: str | None = Field(default=None, max_length=5000)


class OperatorRead(ApiModel):
    id: uuid.UUID
    name: str
    external_id: str | None
    notes: str | None
    created_at: datetime


class Ref(ApiModel):
    id: uuid.UUID
    name: str


# --- sessions --------------------------------------------------------------------------------------


class SessionFields(BaseModel):
    operator_id: uuid.UUID | None = None
    device_id: uuid.UUID | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    environment: Text200 | None = None
    task: Text200 | None = None
    location: Text200 | None = None
    capture_conditions: dict[str, Any] = Field(
        default_factory=dict, description="e.g. lighting, clutter, camera mount — as entered by the user"
    )
    notes: str | None = Field(default=None, max_length=10_000)


class SessionCreate(SessionFields):
    name: str | None = Field(
        default=None,
        pattern=SESSION_NAME_PATTERN,
        description="Leave empty to take the next number for `capture_date`",
    )
    capture_date: date | None = Field(
        default=None, description="Date used for the generated name (default: start date, else today, UTC)"
    )


class SessionUpdate(BaseModel):
    operator_id: uuid.UUID | None = None
    device_id: uuid.UUID | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    environment: Text200 | None = None
    task: Text200 | None = None
    location: Text200 | None = None
    capture_conditions: dict[str, Any] | None = None
    notes: str | None = Field(default=None, max_length=10_000)


class SessionRead(ApiModel):
    id: uuid.UUID
    name: str
    operator: Ref | None
    device: Ref | None
    started_at: datetime | None
    ended_at: datetime | None
    environment: str | None
    task: str | None
    location: str | None
    capture_conditions: dict[str, Any]
    notes: str | None
    created_at: datetime


class SessionStats(BaseModel):
    video_count: int
    ready_count: int
    processing_count: int
    corrupt_count: int
    total_duration_s: float | None
    total_size_bytes: int


class SessionSummary(SessionRead):
    stats: SessionStats


class UploadProblem(BaseModel):
    upload_id: uuid.UUID
    filename: str
    status: UploadStatus
    error: str | None
    created_at: datetime


class VideoProblem(BaseModel):
    video_id: uuid.UUID
    filename: str
    error: str | None


class SessionDetail(SessionSummary):
    datasets: list[Ref]
    failed_uploads: list[UploadProblem]
    corrupt_videos: list[VideoProblem]
    active_uploads: int


class NextSessionName(BaseModel):
    name: str


# --- datasets --------------------------------------------------------------------------------------


class DatasetCreate(BaseModel):
    name: Name
    description: str | None = Field(default=None, max_length=5000)


class DatasetRead(ApiModel):
    id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime


class DatasetSummary(DatasetRead):
    session_count: int
    version_count: int = 0
    latest_version: int | None = None


class DatasetMembership(BaseModel):
    session_id: uuid.UUID


# --- videos ----------------------------------------------------------------------------------------


class VideoSummary(ApiModel):
    id: uuid.UUID
    original_filename: str
    session: Ref | None
    status: VideoStatus
    source_kind: VideoSource
    duration_s: float | None
    width: int | None
    height: int | None
    fps: float | None
    codec: str | None
    frame_count: int | None
    size_bytes: int
    has_audio: bool | None
    error: str | None
    created_at: datetime
    thumbnails_url: str | None = None


class SidecarRead(ApiModel):
    id: uuid.UUID
    filename: str
    format: str
    sha256: str
    parsed: Any
    error: str | None
    created_at: datetime


class LineageRef(BaseModel):
    parent_type: str
    parent_id: uuid.UUID
    relation: str
    job_id: uuid.UUID | None
    created_at: datetime


class VideoDetail(VideoSummary):
    sha256: str
    storage_key: str
    source_path: str | None
    bit_rate: int | None
    upload_id: uuid.UUID | None
    probe: dict[str, Any] | None
    camera_metadata: dict[str, Any] | None
    derivatives: dict[str, Any]
    proxy_url: str | None = None
    sidecars: list[SidecarRead] = []
    lineage: list[LineageRef] = []


class VideoUpdate(BaseModel):
    session_id: uuid.UUID | None = None
