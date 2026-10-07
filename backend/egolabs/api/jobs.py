import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from egolabs.api.deps import AdminUser, CurrentUser, DbSession
from egolabs.jobs import enqueue_job
from egolabs.models import Job, JobLog
from egolabs.schemas import JobLogPage, JobLogRead, JobRead

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("/healthcheck", response_model=JobRead, status_code=status.HTTP_202_ACCEPTED)
def enqueue_healthcheck(db: DbSession, admin: AdminUser) -> Job:
    """Queue a `system.healthcheck` job to confirm a worker is consuming the queue."""
    return enqueue_job(db, "system.healthcheck", created_by=admin.id)


@router.get("/{job_id}", response_model=JobRead)
def get_job(job_id: uuid.UUID, db: DbSession, _: CurrentUser) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return job


@router.get("/{job_id}/logs", response_model=JobLogPage)
def get_job_logs(
    job_id: uuid.UUID,
    db: DbSession,
    _: CurrentUser,
    after_id: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> JobLogPage:
    """Job log lines in order, cursor-paginated so long jobs can be tailed without loading everything."""
    if db.get(Job, job_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    rows = db.scalars(
        select(JobLog).where(JobLog.job_id == job_id, JobLog.id > after_id).order_by(JobLog.id).limit(limit)
    ).all()
    return JobLogPage(
        items=[JobLogRead.model_validate(r) for r in rows],
        next_after_id=rows[-1].id if len(rows) == limit else None,
    )
