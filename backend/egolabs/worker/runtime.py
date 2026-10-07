"""
Job runtime shared by every worker task.

A job is a row in `jobs`; the Celery task only carries its id. `run_job` moves the row through
queued → running → succeeded/failed and every step writes structured `job_logs` rows (principle 7).
Handlers are registered per job type with `@job_handler("type")`.
"""

import logging
import threading
import traceback
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, update
from sqlalchemy.orm import Session, sessionmaker

from egolabs.db import get_sessionmaker
from egolabs.events import record_event
from egolabs.models import Job, JobLog, JobStatus, LogLevel

log = logging.getLogger("egolabs.jobs")

Handler = Callable[["JobContext", dict[str, Any]], dict[str, Any] | None]
_HANDLERS: dict[str, Handler] = {}


def job_handler(job_type: str) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        if job_type in _HANDLERS:
            raise ValueError(f"Duplicate handler for job type {job_type!r}")
        _HANDLERS[job_type] = fn
        return fn

    return register


def registered_job_types() -> list[str]:
    return sorted(_HANDLERS)


class JobContext:
    """Passed to handlers. Each log line is committed immediately so it survives a crash."""

    def __init__(self, job_id: uuid.UUID, job_type: str, sessions: sessionmaker[Session]):
        self.job_id = job_id
        self.job_type = job_type
        self._sessions = sessions

    def log(self, level: LogLevel | str, message: str, **data: Any) -> None:
        level = LogLevel(level)
        with self._sessions() as db:
            db.add(JobLog(job_id=self.job_id, level=level, message=message, data=data))
            db.commit()
        log.log(
            logging.getLevelName(level.value.upper()),
            message,
            extra={"job_id": str(self.job_id), "job_type": self.job_type, "data": data},
        )

    def info(self, message: str, **data: Any) -> None:
        self.log(LogLevel.info, message, **data)

    def warning(self, message: str, **data: Any) -> None:
        self.log(LogLevel.warning, message, **data)

    def session(self) -> Session:
        """A fresh DB session for handler work."""
        return self._sessions()


def run_job(job_id: uuid.UUID | str, sessions: sessionmaker[Session] | None = None) -> JobStatus:
    sessions = sessions or get_sessionmaker()
    job_id = uuid.UUID(str(job_id))

    with sessions() as db:
        job = db.get(Job, job_id, with_for_update=True)
        if job is None:
            log.error("job not found", extra={"job_id": str(job_id)})
            return JobStatus.failed
        if job.status in (JobStatus.succeeded, JobStatus.cancelled, JobStatus.running):
            # Duplicate delivery (acks_late redelivery) or cancelled before start. Jobs orphaned in
            # `running` by a dead worker stop sending heartbeats; the scheduler tick recovers them.
            log.warning("job not runnable", extra={"job_id": str(job_id), "status": job.status.value})
            return job.status
        job.status = JobStatus.running
        job.started_at = job.heartbeat_at = datetime.now(UTC)
        job.attempts += 1
        job_type, payload, attempt = job.type, dict(job.payload), job.attempts
        db.commit()

    ctx = JobContext(job_id, job_type, sessions)
    ctx.info("Job started", attempt=attempt)
    handler = _HANDLERS.get(job_type)
    stop = _heartbeat(job_id, sessions)

    try:
        if handler is None:
            raise LookupError(f"No handler registered for job type {job_type!r}")
        result = handler(ctx, payload) or {}
    except Exception as exc:
        stop()
        ctx.log(LogLevel.error, "Job failed", error=str(exc), traceback=traceback.format_exc())
        with sessions() as db:
            job = db.get(Job, job_id)
            assert job is not None
            job.status = JobStatus.failed
            job.error = f"{type(exc).__name__}: {exc}"
            job.finished_at = datetime.now(UTC)
            record_event(
                db,
                "job.failed",
                f"Job failed: {job_type}",
                entity_type="job",
                entity_id=job_id,
                data={"error": job.error},
            )
            db.commit()
        return JobStatus.failed

    stop()
    with sessions() as db:
        job = db.get(Job, job_id)
        assert job is not None
        job.status = JobStatus.succeeded
        job.result = result
        job.finished_at = datetime.now(UTC)
        db.commit()
    ctx.info("Job succeeded")
    return JobStatus.succeeded


def _heartbeat(job_id: uuid.UUID, sessions: sessionmaker[Session]) -> Callable[[], None]:
    """Touch `jobs.heartbeat_at` every few seconds while the handler runs; returns a function that stops it."""
    from egolabs.config import get_settings

    interval = get_settings().job_heartbeat_s
    done = threading.Event()

    def beat() -> None:
        while not done.wait(interval):
            try:
                with sessions() as db:
                    db.execute(update(Job).where(Job.id == job_id).values(heartbeat_at=func.now()))
                    db.commit()
            except Exception as exc:  # noqa: BLE001 - a missed beat is logged; the job carries on
                log.warning("heartbeat failed", extra={"job_id": str(job_id), "error": str(exc)})

    thread = threading.Thread(target=beat, name=f"heartbeat-{job_id}", daemon=True)
    thread.start()

    def stop() -> None:
        done.set()
        thread.join(timeout=5)

    return stop
