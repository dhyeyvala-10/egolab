"""Dataset → Session → Video → Frame hierarchy, plus the devices and operators that capture sessions."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from egolabs.models.base import Base, CreatedAt, UUIDPk, str_enum
from egolabs.models.enums import ProcessingHold, VideoSource, VideoStatus

dataset_sessions = Table(
    "dataset_sessions",
    Base.metadata,
    Column("dataset_id", UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="CASCADE"), primary_key=True),
    Column("session_id", UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True),
    Column("added_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)


class Dataset(UUIDPk, CreatedAt, Base):
    __tablename__ = "datasets"

    name: Mapped[str] = mapped_column(String(200), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    sessions: Mapped[list["CaptureSession"]] = relationship(
        secondary=dataset_sessions, back_populates="datasets"
    )


class Device(UUIDPk, CreatedAt, Base):
    __tablename__ = "devices"

    name: Mapped[str] = mapped_column(String(200), unique=True)
    kind: Mapped[str | None] = mapped_column(String(100))  # e.g. head-mounted camera, phone
    serial: Mapped[str | None] = mapped_column(String(200))
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict, server_default="{}")


class Operator(UUIDPk, CreatedAt, Base):
    __tablename__ = "operators"

    name: Mapped[str] = mapped_column(String(200))
    external_id: Mapped[str | None] = mapped_column(String(200), unique=True)
    notes: Mapped[str | None] = mapped_column(Text)


class CaptureSession(UUIDPk, CreatedAt, Base):
    """A recording session. Named `SESSION_YYYY_MM_DD_NNN` (spec Phase 1)."""

    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint(r"name ~ '^SESSION_[0-9]{4}_[0-9]{2}_[0-9]{2}_[0-9]{3}$'", name="name_format"),
    )

    name: Mapped[str] = mapped_column(String(64), unique=True)
    operator_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("operators.id", ondelete="SET NULL"), index=True
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("devices.id", ondelete="SET NULL"), index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    environment: Mapped[str | None] = mapped_column(String(200))
    task: Mapped[str | None] = mapped_column(String(200))
    location: Mapped[str | None] = mapped_column(String(200))
    capture_conditions: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    notes: Mapped[str | None] = mapped_column(Text)

    datasets: Mapped[list[Dataset]] = relationship(secondary=dataset_sessions, back_populates="sessions")
    videos: Mapped[list["Video"]] = relationship(back_populates="session")
    operator: Mapped[Operator | None] = relationship()
    device: Mapped[Device | None] = relationship()


class Video(UUIDPk, CreatedAt, Base):
    """An ingested source file. `storage_key` points at the immutable raw object (principle 2)."""

    __tablename__ = "videos"

    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL"), index=True
    )
    original_filename: Mapped[str] = mapped_column(String(1024))
    storage_key: Mapped[str] = mapped_column(String(1024), unique=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)  # exact-duplicate guard
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[VideoStatus] = mapped_column(
        str_enum(VideoStatus, "video_status"), default=VideoStatus.uploaded
    )
    source_kind: Mapped[VideoSource] = mapped_column(
        str_enum(VideoSource, "video_source"), default=VideoSource.file, server_default=VideoSource.file.value
    )
    # Where it came from: the upload, and for archive members the path inside the archive.
    upload_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("uploads.id", ondelete="SET NULL", use_alter=True), index=True
    )
    source_path: Mapped[str | None] = mapped_column(String(1024))
    # ffprobe output (filled by the ingest worker; null until probed). Never estimated.
    duration_s: Mapped[float | None] = mapped_column(Float)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    fps: Mapped[float | None] = mapped_column(Float)
    codec: Mapped[str | None] = mapped_column(String(64))
    bit_rate: Mapped[int | None] = mapped_column(BigInteger)
    has_audio: Mapped[bool | None] = mapped_column(Boolean)
    frame_count: Mapped[int | None] = mapped_column(BigInteger)
    probe: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    camera_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    proxy_key: Mapped[str | None] = mapped_column(String(1024))
    thumbnails_key: Mapped[str | None] = mapped_column(String(1024))
    # Parameters of the derived proxy and thumbnail strip (sizes, frame rate, tile layout).
    derivatives: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    # Quality flags the dataset builder can filter on (egolabs.quality; Phase 7 checks add more).
    quality_flags: Mapped[list[str]] = mapped_column(ARRAY(String(32)), default=list, server_default="{}")
    # Longer than the owner's limit: nothing processes it until they allow it (egolabs.approvals).
    processing_hold: Mapped[ProcessingHold | None] = mapped_column(
        str_enum(ProcessingHold, "processing_hold")
    )
    hold_reason: Mapped[str | None] = mapped_column(Text)

    session: Mapped[CaptureSession | None] = relationship(back_populates="videos")


class Frame(UUIDPk, CreatedAt, Base):
    """
    Frames are indexed lazily: a row exists only once something references that frame
    (an annotation, a lineage edge, a quality flag). Never one row per frame at ingest.
    """

    __tablename__ = "frames"
    __table_args__ = (
        UniqueConstraint("video_id", "frame_index"),
        CheckConstraint("frame_index >= 0", name="frame_index_non_negative"),
    )

    video_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"))
    frame_index: Mapped[int] = mapped_column(Integer)
    timestamp_s: Mapped[float | None] = mapped_column(Float)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict, server_default="{}")
