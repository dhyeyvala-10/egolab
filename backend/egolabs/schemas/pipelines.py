"""Pipelines, versions, runs, steps, logs, schedules, quality checks, and annotated videos (spec Phase 7)."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from egolabs.models.enums import BuildStatus, LogLevel, PipelineRunStatus, RunTrigger, StepStatus
from egolabs.pipelines.inputs import RunInputs
from egolabs.schemas import ApiModel
from egolabs.schemas.annotation import UserRef
from egolabs.schemas.catalog import Ref

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class StepTypeRead(BaseModel):
    key: str
    label: str
    category: str
    per_video: bool
    description: str
    requires: list[str]
    uses: list[str]
    defaults: dict[str, Any]
    config_schema: dict[str, Any]


class GraphError(BaseModel):
    node_id: str | None
    message: str


class GraphIn(BaseModel):
    """`{"nodes": [{"id", "type", "config", "retries"}], "edges": [{"from", "to"}]}`"""

    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)


class GraphCheck(BaseModel):
    ok: bool
    errors: list[GraphError]
    graph: dict[str, Any] | None  # normalized: each config with its defaults


class TemplateRead(BaseModel):
    key: str
    name: str
    description: str
    graph: dict[str, Any]
    layout: dict[str, Any]


class PipelineCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    description: str | None = Field(None, max_length=5000)
    is_template: bool = False
    run_on_upload: bool = Field(False, description="Run on every newly uploaded video once it's ready")
    graph: GraphIn | None = None
    layout: dict[str, Any] | None = None
    from_template: str | None = Field(None, description="A built-in template's key to copy")
    from_pipeline_id: uuid.UUID | None = Field(None, description="A pipeline (or saved template) to copy")
    note: str | None = Field(None, max_length=2000)


class PipelineUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    description: str | None = Field(None, max_length=5000)
    is_template: bool | None = None
    run_on_upload: bool | None = None
    graph: GraphIn | None = Field(None, description="A changed graph becomes the next version")
    layout: dict[str, Any] | None = None
    note: str | None = Field(None, max_length=2000)


class VersionBrief(ApiModel):
    id: uuid.UUID
    number: int
    note: str | None
    created_at: datetime
    created_by: UserRef | None = None


class VersionRead(VersionBrief):
    graph: dict[str, Any]
    graph_hash: str
    parent_version_id: uuid.UUID | None


class RunBrief(BaseModel):
    id: uuid.UUID
    number: int
    status: PipelineRunStatus
    created_at: datetime


class PipelineSummary(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    is_template: bool
    run_on_upload: bool
    latest_version: int
    step_count: int
    run_count: int
    last_run: RunBrief | None
    schedule_count: int
    created_at: datetime
    updated_at: datetime


class PipelineDetail(PipelineSummary):
    layout: dict[str, Any]
    version: VersionRead
    versions: list[VersionBrief]


class RunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inputs: RunInputs
    version: int | None = Field(None, description="Version number to run (default: the latest)")


class RunSummary(BaseModel):
    id: uuid.UUID
    number: int
    pipeline: Ref
    version: int
    status: PipelineRunStatus
    trigger: RunTrigger
    schedule_id: uuid.UUID | None
    video_count: int
    inputs_label: str
    counts: dict[str, int]  # steps by status
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    duration_s: float | None
    error: str | None
    created_by: UserRef | None
    job_id: uuid.UUID | None


class NodeProgress(BaseModel):
    node_id: str
    step_type: str
    label: str
    per_video: bool
    counts: dict[str, int]
    attempts: int
    seconds: float  # total time its attempts ran


class RunDetail(RunSummary):
    graph: dict[str, Any]
    layout: dict[str, Any]
    nodes: list[NodeProgress]
    inputs: dict[str, Any]


class AttemptRead(ApiModel):
    id: uuid.UUID
    number: int
    status: StepStatus
    reason: str
    job_id: uuid.UUID | None
    error: str | None
    error_kind: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class StepRead(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    node_id: str
    step_type: str
    label: str
    video: Ref | None
    status: StepStatus
    attempts: int
    max_attempts: int
    error: str | None
    error_kind: str | None
    error_label: str | None
    retry_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    duration_s: float | None
    result: dict[str, Any]
    job_id: uuid.UUID | None
    attempt_list: list[AttemptRead] = Field(default_factory=list)


class RetryIn(BaseModel):
    step_ids: list[uuid.UUID] = Field(default_factory=list, description="Empty: every failed step of the run")


class RetryResult(BaseModel):
    retried: int
    steps: list[StepRead]


class RunLogLine(BaseModel):
    id: int
    ts: datetime
    level: LogLevel
    message: str
    data: dict[str, Any]
    job_id: uuid.UUID
    source: str  # "run" (the engine) or the step's label
    node_id: str | None
    step_run_id: uuid.UUID | None
    attempt: int | None
    video: Ref | None


class RunLogPage(BaseModel):
    items: list[RunLogLine]
    next_after_id: int | None
    matched: int  # lines matching the filters (counted up to 100,000)
    total: int  # all lines of the run


class ScheduleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pipeline_id: uuid.UUID
    name: Name
    cron: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    timezone: str = "UTC"
    enabled: bool = True
    inputs: RunInputs
    only_new: bool = True


class ScheduleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    cron: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)] | None = None
    timezone: str | None = None
    enabled: bool | None = None
    inputs: RunInputs | None = None
    only_new: bool | None = None


class ScheduleRead(BaseModel):
    id: uuid.UUID
    pipeline: Ref
    name: str
    cron: str
    timezone: str
    enabled: bool
    inputs: dict[str, Any]
    inputs_label: str
    only_new: bool
    next_run_at: datetime | None
    upcoming: list[datetime]
    last_run_at: datetime | None
    last_outcome: str | None
    run_count: int
    last_run: RunBrief | None
    created_at: datetime


class CronPreviewIn(BaseModel):
    cron: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    timezone: str = "UTC"


class CronPreview(BaseModel):
    ok: bool
    error: str | None
    upcoming: list[datetime]


class AnnotatedVideoCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_side: int = Field(720, ge=240, le=2160)
    codec: str = Field("h264", pattern="^(h264|vp9)$")
    skeleton: bool = True
    objects: bool = True
    events: bool = True


class AnnotatedVideoRead(ApiModel):
    id: uuid.UUID
    video_id: uuid.UUID
    status: BuildStatus
    size_bytes: int | None
    codec: str | None
    width: int | None
    height: int | None
    frames: int | None
    duration_s: float | None
    sha256: str | None
    inputs: dict[str, Any]
    options: dict[str, Any]
    job_id: uuid.UUID | None
    created_at: datetime
    finished_at: datetime | None
    error: str | None


class Download(BaseModel):
    url: str
    filename: str
    expires_s: int


class QualityCheckRead(ApiModel):
    id: uuid.UUID
    check: str
    flag: str
    flagged: bool
    metrics: dict[str, Any]
    config: dict[str, Any]
    job_id: uuid.UUID | None
    created_at: datetime


class VideoQuality(BaseModel):
    flags: list[str]
    checks: list[QualityCheckRead]  # the latest of each check
