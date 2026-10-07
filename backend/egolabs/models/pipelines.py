import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from egolabs.models.base import Base, CreatedAt, UUIDPk, str_enum
from egolabs.models.enums import BuildStatus, PipelineRunStatus, RunTrigger, StepStatus


class Pipeline(UUIDPk, CreatedAt, Base):
    """
    A named processing pipeline (spec Phase 7). What it does lives in its versions; `layout` is only where
    the builder draws each node, so moving a node never makes a new version.
    """

    __tablename__ = "pipelines"

    name: Mapped[str] = mapped_column(String(200), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    is_template: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Run on every newly uploaded video as soon as it's ready (see `pipelines/auto.py`).
    run_on_upload: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    layout: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PipelineVersion(UUIDPk, CreatedAt, Base):
    """
    One immutable version of a pipeline's graph (principle 3): `{"nodes": [{id, type, config}], "edges":
    [{from, to}]}`. Saving a changed graph makes the next version, with the previous one as its parent; a
    pipeline started from a template has the template's version as its parent. A trigger refuses changes.
    """

    __tablename__ = "pipeline_versions"
    __table_args__ = (UniqueConstraint("pipeline_id", "number"),)

    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pipelines.id", ondelete="RESTRICT"), index=True
    )
    number: Mapped[int] = mapped_column(Integer)
    graph: Mapped[dict[str, Any]] = mapped_column(JSONB)
    graph_hash: Mapped[str] = mapped_column(String(64))
    parent_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("pipeline_versions.id", ondelete="RESTRICT")
    )
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class PipelineSchedule(UUIDPk, CreatedAt, Base):
    """Runs a pipeline's latest version on a cron schedule, in `timezone`, on the videos `inputs` selects."""

    __tablename__ = "pipeline_schedules"

    pipeline_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pipelines.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    cron: Mapped[str] = mapped_column(String(120))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", server_default="UTC")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    # Only the selected videos this pipeline hasn't yet processed in a successful run.
    only_new: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_outcome: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PipelineRun(UUIDPk, CreatedAt, Base):
    """
    One run of a pipeline version on a pinned set of videos. `job_id` is the run's own log (what the
    engine did: started, queued, retried, finished); each step attempt has its own job and log.
    """

    __tablename__ = "pipeline_runs"
    __table_args__ = (
        UniqueConstraint("pipeline_id", "number"),
        Index("ix_pipeline_runs_status_created_at", "status", "created_at"),
    )

    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pipelines.id", ondelete="RESTRICT"), index=True
    )
    number: Mapped[int] = mapped_column(Integer)
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pipeline_versions.id", ondelete="RESTRICT"))
    status: Mapped[PipelineRunStatus] = mapped_column(
        str_enum(PipelineRunStatus, "pipeline_run_status"), default=PipelineRunStatus.running
    )
    trigger: Mapped[RunTrigger] = mapped_column(str_enum(RunTrigger, "pipeline_run_trigger"))
    schedule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("pipeline_schedules.id", ondelete="SET NULL"), index=True
    )
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB)  # the selector as asked, and the videos it pinned
    video_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class PipelineStepRun(UUIDPk, CreatedAt, Base):
    """
    A node of the run's graph, for one video (per-video steps) or once for the run (dataset build, export).
    `result` is what downstream steps read: e.g. the model run a tracking step made. Retrying a failed step
    makes a new attempt of this row only; finished steps are never run again.
    """

    __tablename__ = "pipeline_step_runs"
    __table_args__ = (
        UniqueConstraint("run_id", "node_id", "video_id", postgresql_nulls_not_distinct=True),
        Index("ix_pipeline_step_runs_run_id_node_id_status", "run_id", "node_id", "status"),
        Index("ix_pipeline_step_runs_status_retry_at", "status", "retry_at"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pipeline_runs.id", ondelete="CASCADE"), index=True)
    node_id: Mapped[str] = mapped_column(String(64))
    step_type: Mapped[str] = mapped_column(String(64))
    video_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("videos.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[StepStatus] = mapped_column(
        str_enum(StepStatus, "pipeline_step_status"), default=StepStatus.pending
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    error: Mapped[str | None] = mapped_column(Text)
    error_kind: Mapped[str | None] = mapped_column(String(32))
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PipelineStepAttempt(UUIDPk, CreatedAt, Base):
    """One try at a step: its own job (and so its own log), why it ran, and how it ended."""

    __tablename__ = "pipeline_step_attempts"
    __table_args__ = (UniqueConstraint("step_run_id", "number"),)

    step_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pipeline_step_runs.id", ondelete="CASCADE"), index=True
    )
    number: Mapped[int] = mapped_column(Integer)
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), index=True)
    status: Mapped[StepStatus] = mapped_column(
        str_enum(StepStatus, "pipeline_attempt_status"), default=StepStatus.queued
    )
    reason: Mapped[str] = mapped_column(String(32))  # first, auto_retry, manual_retry
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    error: Mapped[str | None] = mapped_column(Text)
    error_kind: Mapped[str | None] = mapped_column(String(32))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class VideoQualityCheck(UUIDPk, CreatedAt, Base):
    """One quality check of a video (blur, low light, occlusion, near-duplicates): its measurements, the
    thresholds it was held to, and whether it set its flag on the video."""

    __tablename__ = "video_quality_checks"
    __table_args__ = (
        Index("ix_video_quality_checks_video_id_check_created_at", "video_id", "check", "created_at"),
    )

    video_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"))
    check: Mapped[str] = mapped_column(String(32))
    flag: Mapped[str] = mapped_column(String(32))
    flagged: Mapped[bool] = mapped_column(Boolean)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))


class VideoFrameHash(Base):
    """
    A sampled frame's 64-bit difference hash, for near-duplicate search. The four 16-bit bands are indexed:
    two hashes within 3 bits of each other always share a band, so candidates come from index lookups.
    """

    __tablename__ = "video_frame_hashes"
    __table_args__ = tuple(Index(f"ix_video_frame_hashes_b{i}", f"b{i}") for i in range(4))

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    video_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    frame: Mapped[int] = mapped_column(Integer)
    hash: Mapped[int] = mapped_column(BigInteger)  # the 64 bits as a signed integer
    b0: Mapped[int] = mapped_column(Integer)
    b1: Mapped[int] = mapped_column(Integer)
    b2: Mapped[int] = mapped_column(Integer)
    b3: Mapped[int] = mapped_column(Integer)


class AnnotatedVideo(UUIDPk, CreatedAt, Base):
    """A video rendered with its hand skeletons, object boxes, and movement events drawn on, to download."""

    __tablename__ = "annotated_videos"

    video_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    status: Mapped[BuildStatus] = mapped_column(
        str_enum(BuildStatus, "annotated_video_status"), default=BuildStatus.building
    )
    storage_key: Mapped[str | None] = mapped_column(String(1024))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(String(64))
    codec: Mapped[str | None] = mapped_column(String(16))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    frames: Mapped[int | None] = mapped_column(Integer)
    duration_s: Mapped[float | None] = mapped_column(Float)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")  # the runs drawn
    options: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
