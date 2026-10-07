import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    true,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from egolabs.models.base import Base, CreatedAt, UUIDPk, str_enum
from egolabs.models.enums import AnnotationSource, MovementEventStatus, ReviewMethod


class MovementClass(UUIDPk, CreatedAt, Base):
    """
    A movement class events can be labelled with (spec Phase 4). The built-in classes are the spec's list;
    teams edit their labels and descriptions, switch classes off, and add their own. Classifiers emit a
    class `name`; a model that emits a name nobody defined adds it as a custom class.
    """

    __tablename__ = "movement_classes"

    name: Mapped[str] = mapped_column(String(64), unique=True)  # stable slug, e.g. pick_up
    label: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    builtin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Inactive classes are not recorded by new classification runs (existing events stay).
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    requires_object: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MovementEvent(UUIDPk, CreatedAt, Base):
    """
    One detected movement (spec Phase 4 event record). Its timeline segment is `annotation_id` (category
    movement), so it appears on the inspector's timeline and goes through the same correction history.

    Events are versioned (Phase 5): correcting one never edits it. The correction is a new event
    (`source=auto_corrected`, `parent_event_id` = the prediction, its own corrected annotation), and the
    prediction is marked `corrected` and `superseded_at`, so both stay readable. Every status change is a
    `MovementEventReview` row saying who (or which auto-accept rule) made it and how.

    `evidence` names the exact keypoint frames that produced it — `{"frames": [[start, end, step], …],
    "measurements": {name: [value per evidence frame]}, "thresholds": {…}, "rule": "…"}` — and the frames are
    rows of the hand-tracking run `hand_run_id` for track `hand_track_id`.
    """

    __tablename__ = "movement_events"
    __table_args__ = (
        CheckConstraint("end_frame >= start_frame", name="frame_range"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        # Principle 8: a prediction carries a confidence; a human correction has none of its own.
        CheckConstraint("source <> 'auto' OR confidence IS NOT NULL", name="auto_has_confidence"),
        CheckConstraint("source = 'auto' OR parent_event_id IS NOT NULL", name="correction_has_parent"),
        CheckConstraint(
            "disagreement IS NULL OR (disagreement >= 0 AND disagreement <= 1)", name="disagreement_range"
        ),
        Index("ix_movement_events_video_id_start_frame", "video_id", "start_frame"),
        Index("ix_movement_events_class_id_status", "class_id", "status"),
    )

    annotation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("annotations.id", ondelete="CASCADE"), unique=True
    )
    video_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"))
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL"), index=True
    )
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cv_runs.id", ondelete="CASCADE"), index=True)
    hand_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cv_runs.id", ondelete="CASCADE"))
    object_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cv_runs.id", ondelete="CASCADE"))
    model_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("model_versions.id", ondelete="RESTRICT"), index=True
    )
    class_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("movement_classes.id", ondelete="RESTRICT"), index=True
    )
    start_frame: Mapped[int] = mapped_column(Integer)
    end_frame: Mapped[int] = mapped_column(Integer)
    start_s: Mapped[float] = mapped_column(Float)
    end_s: Mapped[float] = mapped_column(Float)
    handedness: Mapped[str] = mapped_column(String(8))
    hand_track_id: Mapped[int] = mapped_column(Integer)
    fingers: Mapped[list[str]] = mapped_column(ARRAY(String(8)), default=list, server_default="{}")
    object_track_id: Mapped[int | None] = mapped_column(Integer)
    object_label: Mapped[str | None] = mapped_column(String(100))
    confidence: Mapped[float | None] = mapped_column(Float)
    status: Mapped[MovementEventStatus] = mapped_column(
        str_enum(MovementEventStatus, "movement_event_status"),
        default=MovementEventStatus.auto_detected,
        server_default=MovementEventStatus.auto_detected.value,
        index=True,
    )
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # How the current status was set, and the batch or rule that set it (None: never reviewed).
    review_method: Mapped[ReviewMethod | None] = mapped_column(str_enum(ReviewMethod, "review_method"))
    review_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("review_batches.id", ondelete="SET NULL")
    )
    review_rule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("review_rules.id", ondelete="SET NULL")
    )

    # Versions (Phase 5): a correction is a new event whose parent is the prediction.
    source: Mapped[AnnotationSource] = mapped_column(
        str_enum(AnnotationSource, "movement_event_source"),
        default=AnnotationSource.auto,
        server_default=AnnotationSource.auto.value,
    )
    parent_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("movement_events.id", ondelete="RESTRICT"), index=True
    )
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Active learning: 1 − agreement with other model versions' latest runs on this video (None: no other
    # model version has classified it), and how many versions it was compared with.
    disagreement: Mapped[float | None] = mapped_column(Float)
    compared_versions: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class ReviewRule(UUIDPk, CreatedAt, Base):
    """
    Auto-accept: new predictions at or above `min_confidence` are confirmed without a person (method
    `auto_rule`). A rule with no class is the default for classes without their own. Events flagged for
    review are never auto-accepted.
    """

    __tablename__ = "review_rules"
    __table_args__ = (
        CheckConstraint("min_confidence >= 0 AND min_confidence <= 1", name="min_confidence_range"),
        Index("uq_review_rules_class_id", "class_id", unique=True, postgresql_nulls_not_distinct=True),
    )

    class_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("movement_classes.id", ondelete="CASCADE"))
    min_confidence: Mapped[float] = mapped_column(Float)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class ReviewBatch(UUIDPk, CreatedAt, Base):
    """One bulk accept or reject: the filters it was given, how many events it changed, and its undo."""

    __tablename__ = "review_batches"

    action: Mapped[MovementEventStatus] = mapped_column(str_enum(MovementEventStatus, "review_batch_action"))
    filters: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    undone_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    undone_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class MovementEventReview(UUIDPk, CreatedAt, Base):
    """Append-only review log: one row per status change of an event."""

    __tablename__ = "movement_event_reviews"
    __table_args__ = (
        Index("ix_movement_event_reviews_event_id_created_at", "event_id", "created_at"),
        Index("ix_movement_event_reviews_actor_id_created_at", "actor_id", "created_at"),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("movement_events.id", ondelete="CASCADE"))
    from_status: Mapped[MovementEventStatus | None] = mapped_column(
        str_enum(MovementEventStatus, "review_from_status")
    )
    to_status: Mapped[MovementEventStatus] = mapped_column(str_enum(MovementEventStatus, "review_to_status"))
    method: Mapped[ReviewMethod] = mapped_column(str_enum(ReviewMethod, "review_log_method"))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("review_batches.id", ondelete="SET NULL"), index=True
    )
    rule_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("review_rules.id", ondelete="SET NULL"))
    # The new version, for a correction
    related_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("movement_events.id", ondelete="SET NULL")
    )
    # The event's class when reviewed (per-class metrics survive a later correction to another class)
    class_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("movement_classes.id", ondelete="SET NULL"))
