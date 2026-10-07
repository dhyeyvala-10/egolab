import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    false,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from egolabs.models.base import Base, CreatedAt, UUIDPk, str_enum
from egolabs.models.enums import AnnotationCategory, AnnotationSource, AnnotationType, RevisionAction

if TYPE_CHECKING:
    from egolabs.models.users import User


class ModelVersion(UUIDPk, CreatedAt, Base):
    """A registered CV/ML adapter version (principle 10). Every prediction references one (principle 8)."""

    __tablename__ = "model_versions"
    __table_args__ = (UniqueConstraint("name", "version"),)

    name: Mapped[str] = mapped_column(String(200))  # e.g. mediapipe-hands
    version: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(100))  # hand_tracking, movement_classification, object_detection
    adapter: Mapped[str] = mapped_column(String(300))  # import path of the adapter class
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    keypoint_schema: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")


class Annotation(UUIDPk, CreatedAt, Base):
    """
    A temporal segment, bounding box, or keypoint set on a video frame range.

    Corrections never overwrite: a human correction is a new row with `source=auto_corrected` and
    `parent_annotation_id` pointing at the original prediction (principle 5), and the prediction is
    marked `superseded_at`. Deletes are soft. Every change appends an `AnnotationRevision`.

    Box and keypoint coordinates in `data` are normalised to the frame (0–1, origin top left), so they
    hold for the raw video and its proxy alike.
    """

    __tablename__ = "annotations"
    __table_args__ = (
        CheckConstraint("frame_end >= frame_start", name="frame_range"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="confidence_range"
        ),
        # Principle 8: every prediction carries a confidence score and a model version.
        CheckConstraint(
            "source <> 'auto' OR (confidence IS NOT NULL AND model_version_id IS NOT NULL)",
            name="auto_has_confidence_and_model",
        ),
        CheckConstraint("source = 'auto' OR created_by IS NOT NULL", name="human_has_author"),
        CheckConstraint(
            "source <> 'auto_corrected' OR parent_annotation_id IS NOT NULL", name="correction_has_parent"
        ),
        CheckConstraint("frame_start >= 0", name="frame_start_non_negative"),
        Index("ix_annotations_video_id_frame_start", "video_id", "frame_start"),
    )

    video_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"))
    type: Mapped[AnnotationType] = mapped_column(str_enum(AnnotationType, "annotation_type"))
    label: Mapped[str] = mapped_column(String(200))
    frame_start: Mapped[int] = mapped_column(Integer)
    frame_end: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")  # bbox / keypoints
    source: Mapped[AnnotationSource] = mapped_column(str_enum(AnnotationSource, "annotation_source"))
    confidence: Mapped[float | None] = mapped_column(Float)
    model_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("model_versions.id", ondelete="RESTRICT"), index=True
    )
    parent_annotation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("annotations.id", ondelete="RESTRICT"), index=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    category: Mapped[AnnotationCategory] = mapped_column(
        str_enum(AnnotationCategory, "annotation_category"),
        default=AnnotationCategory.general,
        server_default=AnnotationCategory.general.value,
    )
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The model run that produced this annotation (AI output only).
    cv_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cv_runs.id", ondelete="SET NULL"), index=True
    )

    author: Mapped["User | None"] = relationship(foreign_keys=[created_by], lazy="raise")


class AnnotationRevision(UUIDPk, CreatedAt, Base):
    """Append-only edit history: one row per change, with the full state after it (`snapshot`)."""

    __tablename__ = "annotation_revisions"
    __table_args__ = (UniqueConstraint("annotation_id", "revision"),)

    annotation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("annotations.id", ondelete="CASCADE"))
    revision: Mapped[int] = mapped_column(Integer)
    action: Mapped[RevisionAction] = mapped_column(str_enum(RevisionAction, "revision_action"))
    # {field: {"from": old, "to": new}} for the fields this revision changed
    changes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # superseded: the correction that replaced this annotation; created: the prediction it corrects
    related_annotation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("annotations.id", ondelete="SET NULL")
    )

    actor: Mapped["User | None"] = relationship(lazy="raise")
