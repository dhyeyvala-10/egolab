from fastapi import APIRouter
from sqlalchemy import ColumnElement, Select, and_, func, or_, select

from egolabs.api.deps import CurrentUser, DbSession
from egolabs.models import ACTIVE_JOB_STATUSES, CaptureSession, Dataset, Event, Job, Role, Upload, User, Video
from egolabs.schemas import ActivityEvent, JobSummary, OverviewCounts, OverviewResponse

router = APIRouter(tags=["overview"])

RECENT_JOBS = 10
RECENT_EVENTS = 20


def _own_events(user: User) -> ColumnElement[bool]:
    """Events about what this person did: their actions, and what happened to their uploads and videos."""
    mine = select(Upload.id).where(Upload.created_by == user.id)
    return or_(
        Event.actor_id == user.id,
        and_(Event.entity_type == "upload", Event.entity_id.in_(mine)),
        and_(
            Event.entity_type == "video",
            Event.entity_id.in_(select(Video.id).where(Video.upload_id.in_(mine))),
        ),
    )


@router.get("/overview", response_model=OverviewResponse)
def overview(db: DbSession, user: CurrentUser) -> OverviewResponse:
    """Headline counts and recent activity, computed from the database. The admin sees everyone's activity and
    jobs; anyone else sees only their own (people don't see what others are doing)."""

    def count(stmt: Select[tuple[int]]) -> int:
        return db.scalar(stmt) or 0

    counts = OverviewCounts(
        datasets=count(select(func.count()).select_from(Dataset)),
        sessions=count(select(func.count()).select_from(CaptureSession)),
        videos=count(select(func.count()).select_from(Video)),
        jobs_active=count(select(func.count()).select_from(Job).where(Job.status.in_(ACTIVE_JOB_STATUSES))),
    )
    jobs_q, events_q = select(Job), select(Event)
    if user.role != Role.admin:
        jobs_q, events_q = jobs_q.where(Job.created_by == user.id), events_q.where(_own_events(user))
    jobs = db.scalars(jobs_q.order_by(Job.created_at.desc(), Job.id).limit(RECENT_JOBS)).all()
    events = db.scalars(events_q.order_by(Event.id.desc()).limit(RECENT_EVENTS)).all()
    return OverviewResponse(
        counts=counts,
        recent_jobs=[JobSummary.model_validate(j) for j in jobs],
        recent_events=[ActivityEvent.model_validate(e) for e in events],
    )
