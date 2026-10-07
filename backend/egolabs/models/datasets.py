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
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from egolabs.models.base import Base, CreatedAt, UUIDPk, str_enum
from egolabs.models.enums import BuildStatus, ExportFormat


class DatasetVersion(UUIDPk, CreatedAt, Base):
    """
    An immutable, reproducible training set (spec Phase 6, principle 6).

    `spec` is what was asked (filters and split); `inputs` pins what it was built from: the videos the video
    filters matched, each video's classification run at build time, and the instant `as_of` whose review
    state and annotation revisions it reads. Rebuilding from `spec` + `inputs` gives the same samples and
    `content_hash`, however the data changes later. Once `ready`, a database trigger refuses any change.
    """

    __tablename__ = "dataset_versions"
    __table_args__ = (UniqueConstraint("dataset_id", "number"),)

    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("datasets.id", ondelete="RESTRICT"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    parent_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("dataset_versions.id", ondelete="RESTRICT")
    )
    status: Mapped[BuildStatus] = mapped_column(
        str_enum(BuildStatus, "dataset_version_status"), default=BuildStatus.building
    )
    spec: Mapped[dict[str, Any]] = mapped_column(JSONB)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    sample_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    counts: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    model_version_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), default=list, server_default="{}"
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="RESTRICT"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    built_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)  # what changed and why, from whoever built it


class DatasetVersionSample(Base):
    """
    One sample of a version: a movement event's labelled segment as it stood at the version's `as_of`, with
    its split. Rows are written once and never changed (a trigger refuses updates and deletes).
    """

    __tablename__ = "dataset_version_samples"
    __table_args__ = (
        UniqueConstraint("version_id", "sample_no"),
        Index("ix_dataset_version_samples_version_id_split", "version_id", "split"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dataset_versions.id", ondelete="RESTRICT"))
    sample_no: Mapped[int] = mapped_column(Integer)
    split: Mapped[str] = mapped_column(String(8))
    group_key: Mapped[str] = mapped_column(String(80))
    annotation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("annotations.id", ondelete="RESTRICT"), index=True
    )
    annotation_revision: Mapped[int] = mapped_column(Integer)
    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("movement_events.id", ondelete="RESTRICT"), index=True
    )
    video_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("videos.id", ondelete="RESTRICT"))
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    class_name: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(200))
    start_frame: Mapped[int] = mapped_column(Integer)
    end_frame: Mapped[int] = mapped_column(Integer)
    start_s: Mapped[float] = mapped_column(Float)
    end_s: Mapped[float] = mapped_column(Float)
    handedness: Mapped[str] = mapped_column(String(8))
    hand_track_id: Mapped[int] = mapped_column(Integer)
    fingers: Mapped[list[str]] = mapped_column(ARRAY(String(8)), default=list)
    object_label: Mapped[str | None] = mapped_column(String(100))
    object_track_id: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(
        String(32)
    )  # auto (a prediction) or auto_corrected (a person's correction)
    status: Mapped[str] = mapped_column(String(32))  # review status at as_of
    review_method: Mapped[str | None] = mapped_column(String(32))
    confidence: Mapped[float | None] = mapped_column(Float)
    model_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("model_versions.id", ondelete="RESTRICT"))
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cv_runs.id", ondelete="RESTRICT"))
    hand_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cv_runs.id", ondelete="RESTRICT"))
    object_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cv_runs.id", ondelete="RESTRICT"))


class DatasetVersionCheck(UUIDPk, CreatedAt, Base):
    """A rebuild of a version from its recorded spec and inputs, and whether it gave the same content hash."""

    __tablename__ = "dataset_version_checks"

    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dataset_versions.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[BuildStatus] = mapped_column(
        str_enum(BuildStatus, "dataset_check_status"), default=BuildStatus.building
    )
    content_hash: Mapped[str | None] = mapped_column(String(64))
    sample_count: Mapped[int | None] = mapped_column(Integer)
    matches: Mapped[bool | None] = mapped_column(Boolean)
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class DatasetExport(UUIDPk, CreatedAt, Base):
    """A version written out in one format, as one archive in the derived bucket."""

    __tablename__ = "dataset_exports"

    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dataset_versions.id", ondelete="RESTRICT"), index=True
    )
    format: Mapped[ExportFormat] = mapped_column(str_enum(ExportFormat, "export_format"))
    status: Mapped[BuildStatus] = mapped_column(
        str_enum(BuildStatus, "dataset_export_status"), default=BuildStatus.building
    )
    storage_key: Mapped[str | None] = mapped_column(String(1024))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(String(64))
    files: Mapped[int | None] = mapped_column(Integer)
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
