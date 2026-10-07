"""Upload state and metadata sidecars (spec Phase 1)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from egolabs.models.base import Base, CreatedAt, UUIDPk, str_enum
from egolabs.models.enums import UploadKind, UploadStatus


class Upload(UUIDPk, CreatedAt, Base):
    """
    One file sent from a browser (or the mobile app) straight to object storage as an S3 multipart
    upload. The staging object is ingested by the worker, which moves it to content-addressed raw
    storage, so an upload never overwrites an existing raw file.
    """

    __tablename__ = "uploads"
    __table_args__ = (
        CheckConstraint("size_bytes >= 0", name="size_non_negative"),
        CheckConstraint("sequence_fps IS NULL OR sequence_fps > 0", name="sequence_fps_positive"),
    )

    filename: Mapped[str] = mapped_column(String(1024))
    content_type: Mapped[str | None] = mapped_column(String(200))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[UploadKind] = mapped_column(str_enum(UploadKind, "upload_kind"))
    status: Mapped[UploadStatus] = mapped_column(
        str_enum(UploadStatus, "upload_status"), default=UploadStatus.uploading, index=True
    )
    staging_key: Mapped[str] = mapped_column(String(1024), unique=True)
    s3_upload_id: Mapped[str | None] = mapped_column(String(1024))
    part_size: Mapped[int] = mapped_column(Integer)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL"), index=True
    )
    # User input: frame rate for image sequences inside an archive (never guessed).
    sequence_fps: Mapped[float | None] = mapped_column(Float)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # Primary result: the video created, or the existing video this upload duplicated.
    video_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("videos.id", ondelete="SET NULL"))
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    error: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Why it waits for the owner (over the size limit), and their answer.
    approval_reason: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MetadataFile(UUIDPk, CreatedAt, Base):
    """A JSON or CSV sidecar, stored raw and parsed. Attached to a video when names match, else the session."""

    __tablename__ = "metadata_files"

    upload_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("uploads.id", ondelete="SET NULL"))
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL"), index=True
    )
    video_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("videos.id", ondelete="SET NULL"), index=True
    )
    filename: Mapped[str] = mapped_column(String(1024))
    format: Mapped[str] = mapped_column(String(8))  # json | csv
    storage_key: Mapped[str] = mapped_column(String(1024))
    sha256: Mapped[str] = mapped_column(String(64))
    parsed: Mapped[Any | None] = mapped_column(JSONB)  # null when the file couldn't be parsed
    error: Mapped[str | None] = mapped_column(Text)
