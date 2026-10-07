import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    cast,
    func,
    literal_column,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from egolabs.models.base import Base, CreatedAt, UUIDPk, str_enum
from egolabs.models.enums import JobStatus, LogLevel


class Job(UUIDPk, CreatedAt, Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_status_created_at", "status", "created_at"),)

    type: Mapped[str] = mapped_column(String(100), index=True)  # e.g. ingest.probe, cv.hand_tracking
    status: Mapped[JobStatus] = mapped_column(str_enum(JobStatus, "job_status"), default=JobStatus.queued)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    parent_job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    celery_task_id: Mapped[str | None] = mapped_column(String(255), index=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Written every few seconds while a worker runs the job, so a job whose worker died can be recovered.
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    logs: Mapped[list["JobLog"]] = relationship(back_populates="job", order_by="JobLog.id")


class JobLog(Base):
    """Structured log line written by a job (principle 7)."""

    __tablename__ = "job_logs"
    __table_args__ = (
        Index("ix_job_logs_job_id_id", "job_id", "id"),
        # Trigram search over the message and its data (a pipeline run's logs, spec Phase 7; migration 0008).
        # Queries use the same expression (`search_text`) so the index applies.
        Index(
            "ix_job_logs_search_trgm",
            text("(message || ' ' || data::text) gin_trgm_ops"),
            postgresql_using="gin",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    level: Mapped[LogLevel] = mapped_column(str_enum(LogLevel, "log_level"), default=LogLevel.info)
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")

    job: Mapped[Job] = relationship(back_populates="logs")


def search_text() -> Any:
    """`message || ' ' || data::text`: the expression the trigram index is built on."""
    return JobLog.message.concat(literal_column("' '")).concat(cast(JobLog.data, Text))
