import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from egolabs.models.base import Base, CreatedAt, UUIDPk, str_enum
from egolabs.models.enums import AssignmentStatus


class AnnotationAssignment(UUIDPk, CreatedAt, Base):
    """A session or a single video handed to an annotator (the Annotation Queue)."""

    __tablename__ = "annotation_assignments"
    __table_args__ = (
        CheckConstraint("num_nonnulls(session_id, video_id) = 1", name="one_target"),
        Index("ix_annotation_assignments_assignee_id_status", "assignee_id", "status"),
    )

    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    video_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("videos.id", ondelete="CASCADE"), index=True
    )
    assignee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    status: Mapped[AssignmentStatus] = mapped_column(
        str_enum(AssignmentStatus, "assignment_status"),
        default=AssignmentStatus.todo,
        server_default=AssignmentStatus.todo.value,
    )
    note: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
