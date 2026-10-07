import uuid
from typing import Any

from sqlalchemy.orm import Session

from egolabs.models import Job


def enqueue_job(
    db: Session,
    job_type: str,
    payload: dict[str, Any] | None = None,
    *,
    created_by: uuid.UUID | None = None,
    parent_job_id: uuid.UUID | None = None,
) -> Job:
    """Create the job row, commit it, then hand its id to the worker queue."""
    from egolabs.worker.tasks import run_job_task  # imported lazily: the API process needs no worker setup

    job = Job(type=job_type, payload=payload or {}, created_by=created_by, parent_job_id=parent_job_id)
    db.add(job)
    db.commit()
    result = run_job_task.delay(str(job.id))
    job.celery_task_id = result.id
    db.commit()
    return job
