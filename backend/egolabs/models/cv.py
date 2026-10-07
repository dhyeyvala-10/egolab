import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from egolabs.models.base import Base, CreatedAt, UUIDPk, str_enum
from egolabs.models.enums import CvRunStatus


class CvRun(UUIDPk, CreatedAt, Base):
    """
    One model run over one video (spec Phase 3). Per-frame output lives in Parquet in object storage
    (`output`); this row holds the summary. Every run, and every row it writes, references its model version.
    """

    __tablename__ = "cv_runs"
    __table_args__ = (
        CheckConstraint("stride >= 1", name="stride_positive"),
        Index("ix_cv_runs_video_id_kind_created_at", "video_id", "kind", "created_at"),
    )

    video_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(64))  # a CvRunKind: hand_tracking, object_detection, movement
    # Set by the worker when it loads the adapter (queued runs have none yet).
    model_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("model_versions.id", ondelete="RESTRICT"), index=True
    )

    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    status: Mapped[CvRunStatus] = mapped_column(
        str_enum(CvRunStatus, "cv_run_status"),
        default=CvRunStatus.queued,
        server_default=CvRunStatus.queued.value,
    )
    adapter: Mapped[str] = mapped_column(String(300))  # registry name or import path, as configured
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    stride: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    # Runs whose output this one reads, by kind ({"hand_tracking": run id, ...}). A run with inputs waits
    # until they succeed (status `waiting`), and fails if one of them fails.
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    frames_total: Mapped[int | None] = mapped_column(Integer)
    frames_processed: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    frames_with_hands: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    detections: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    tracks: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    missing_detections: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    tracking_failures: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    mean_confidence: Mapped[float | None] = mapped_column(Float)
    # {"prefix", "chunk_frames", <table>: [keys], "rows": {...}}; tables: hands + fingers, or objects
    output: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class HandTrack(UUIDPk, CreatedAt, Base):
    """Summary of one tracked hand in a run: the per-frame keypoints are in the run's Parquet files."""

    __tablename__ = "hand_tracks"
    __table_args__ = (
        UniqueConstraint("run_id", "track_id"),
        CheckConstraint("last_frame >= first_frame", name="frame_range"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cv_runs.id", ondelete="CASCADE"), index=True)
    model_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("model_versions.id", ondelete="RESTRICT"))
    track_id: Mapped[int] = mapped_column(Integer)
    handedness: Mapped[str] = mapped_column(String(8))
    first_frame: Mapped[int] = mapped_column(Integer)
    last_frame: Mapped[int] = mapped_column(Integer)
    frames_detected: Mapped[int] = mapped_column(Integer)
    missing_detections: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    mean_confidence: Mapped[float] = mapped_column(Float)
    path_length_px: Mapped[float] = mapped_column(Float)
    mean_speed_px_s: Mapped[float] = mapped_column(Float)
    peak_speed_px_s: Mapped[float] = mapped_column(Float)


class ObjectTrack(UUIDPk, CreatedAt, Base):
    """Summary of one tracked object in an object-detection run; per-frame boxes are in its Parquet files."""

    __tablename__ = "object_tracks"
    __table_args__ = (
        UniqueConstraint("run_id", "track_id"),
        CheckConstraint("last_frame >= first_frame", name="frame_range"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cv_runs.id", ondelete="CASCADE"), index=True)
    model_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("model_versions.id", ondelete="RESTRICT"))
    track_id: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(100))
    first_frame: Mapped[int] = mapped_column(Integer)
    last_frame: Mapped[int] = mapped_column(Integer)
    frames_detected: Mapped[int] = mapped_column(Integer)
    missing_detections: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    mean_score: Mapped[float] = mapped_column(Float)
    max_score: Mapped[float] = mapped_column(Float)
    # Mean box over the track (x, y, w, h normalised to the frame) and how far its centre travelled.
    mean_bbox: Mapped[list[float]] = mapped_column(JSONB)
    path_length_px: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
