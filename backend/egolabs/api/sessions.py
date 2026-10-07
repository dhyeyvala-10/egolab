import uuid
from datetime import UTC, date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import Select, func, or_, select, text
from sqlalchemy.orm import selectinload

from egolabs.api.deps import CurrentUser, DbSession, Writer
from egolabs.events import record_event
from egolabs.models import (
    CaptureSession,
    Dataset,
    Device,
    Operator,
    Upload,
    UploadStatus,
    Video,
    VideoStatus,
    dataset_sessions,
)
from egolabs.schemas import Page
from egolabs.schemas.catalog import (
    NextSessionName,
    Ref,
    SessionCreate,
    SessionDetail,
    SessionRead,
    SessionStats,
    SessionSummary,
    SessionUpdate,
    UploadProblem,
    VideoProblem,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _prefix(day: date) -> str:
    return f"SESSION_{day:%Y_%m_%d}_"


def _next_number(db: DbSession, day: date) -> int:
    last = db.scalar(
        select(func.max(CaptureSession.name)).where(CaptureSession.name.like(f"{_prefix(day)}%"))
    )
    return int(last[-3:]) + 1 if last else 1


def allocate_session_name(db: DbSession, day: date) -> str:
    """Next free SESSION_YYYY_MM_DD_NNN for `day`, serialised per day with an advisory lock."""
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": _prefix(day)})
    n = _next_number(db, day)
    if n > 999:
        raise HTTPException(status.HTTP_409_CONFLICT, f"All 999 session numbers for {day} are used")
    return f"{_prefix(day)}{n:03d}"


def _stats_subquery():
    return (
        select(
            Video.session_id.label("sid"),
            func.count().label("video_count"),
            func.count().filter(Video.status == VideoStatus.ready).label("ready_count"),
            func.count()
            .filter(Video.status.in_([VideoStatus.uploaded, VideoStatus.processing]))
            .label("processing_count"),
            func.count().filter(Video.status == VideoStatus.corrupt).label("corrupt_count"),
            func.sum(Video.duration_s).label("total_duration_s"),
            func.coalesce(func.sum(Video.size_bytes), 0).label("total_size_bytes"),
        )
        .where(Video.session_id.is_not(None))
        .group_by(Video.session_id)
        .subquery()
    )


def _stats(row) -> SessionStats:
    return SessionStats(
        video_count=row.video_count or 0,
        ready_count=row.ready_count or 0,
        processing_count=row.processing_count or 0,
        corrupt_count=row.corrupt_count or 0,
        total_duration_s=row.total_duration_s,
        total_size_bytes=int(row.total_size_bytes or 0),
    )


def _read(session: CaptureSession) -> dict:
    return SessionRead.model_validate(session).model_dump()


def _validate_refs(db: DbSession, operator_id: uuid.UUID | None, device_id: uuid.UUID | None) -> None:
    if operator_id and db.get(Operator, operator_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Operator not found")
    if device_id and db.get(Device, device_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Device not found")


def _validate_times(started_at: datetime | None, ended_at: datetime | None) -> None:
    if started_at and ended_at and ended_at < started_at:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "End time is before start time")


SortKey = Literal["name", "created_at", "started_at", "video_count", "total_duration_s"]


@router.get("", response_model=Page[SessionSummary])
def list_sessions(
    db: DbSession,
    _: CurrentUser,
    q: Annotated[str | None, Query(max_length=200)] = None,
    operator_id: uuid.UUID | None = None,
    device_id: uuid.UUID | None = None,
    dataset_id: uuid.UUID | None = None,
    environment: Annotated[str | None, Query(max_length=200)] = None,
    sort: SortKey = "created_at",
    order: Literal["asc", "desc"] = "desc",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[SessionSummary]:
    stats = _stats_subquery()
    stmt: Select = select(CaptureSession, stats).outerjoin(stats, stats.c.sid == CaptureSession.id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                CaptureSession.name.ilike(like),
                CaptureSession.task.ilike(like),
                CaptureSession.environment.ilike(like),
                CaptureSession.location.ilike(like),
            )
        )
    if operator_id:
        stmt = stmt.where(CaptureSession.operator_id == operator_id)
    if device_id:
        stmt = stmt.where(CaptureSession.device_id == device_id)
    if environment:
        stmt = stmt.where(CaptureSession.environment == environment)
    if dataset_id:
        stmt = stmt.where(
            CaptureSession.id.in_(
                select(dataset_sessions.c.session_id).where(dataset_sessions.c.dataset_id == dataset_id)
            )
        )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    column = {
        "name": CaptureSession.name,
        "created_at": CaptureSession.created_at,
        "started_at": CaptureSession.started_at,
        "video_count": func.coalesce(stats.c.video_count, 0),
        "total_duration_s": stats.c.total_duration_s,
    }[sort]
    direction = column.asc().nulls_last() if order == "asc" else column.desc().nulls_last()
    rows = db.execute(
        stmt.options(selectinload(CaptureSession.operator), selectinload(CaptureSession.device))
        .order_by(direction, CaptureSession.id)
        .limit(limit)
        .offset(offset)
    ).all()
    items = [SessionSummary(**_read(row[0]), stats=_stats(row)) for row in rows]
    return Page[SessionSummary](items=items, total=total, limit=limit, offset=offset)


@router.get("/next-name", response_model=NextSessionName)
def preview_next_name(
    db: DbSession, _: CurrentUser, date_: Annotated[date | None, Query(alias="date")] = None
) -> NextSessionName:
    day = date_ or datetime.now(UTC).date()
    return NextSessionName(name=f"{_prefix(day)}{min(_next_number(db, day), 999):03d}")


def _detail(db: DbSession, session_id: uuid.UUID) -> SessionDetail:
    session = db.get(
        CaptureSession,
        session_id,
        options=[
            selectinload(CaptureSession.operator),
            selectinload(CaptureSession.device),
            selectinload(CaptureSession.datasets),
        ],
    )
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    stats = _stats_subquery()
    row = db.execute(select(stats).where(stats.c.sid == session_id)).first()
    failed = db.scalars(
        select(Upload)
        .where(Upload.session_id == session_id, Upload.status == UploadStatus.failed)
        .order_by(Upload.created_at.desc())
        .limit(50)
    ).all()
    corrupt = db.scalars(
        select(Video)
        .where(Video.session_id == session_id, Video.status == VideoStatus.corrupt)
        .order_by(Video.created_at.desc())
        .limit(50)
    ).all()
    active = db.scalar(
        select(func.count())
        .select_from(Upload)
        .where(
            Upload.session_id == session_id,
            Upload.status.in_([UploadStatus.uploading, UploadStatus.processing]),
        )
    )
    return SessionDetail(
        **_read(session),
        stats=_stats(row)
        if row
        else SessionStats(
            video_count=0,
            ready_count=0,
            processing_count=0,
            corrupt_count=0,
            total_duration_s=None,
            total_size_bytes=0,
        ),
        datasets=[Ref(id=d.id, name=d.name) for d in sorted(session.datasets, key=lambda d: d.name)],
        failed_uploads=[
            UploadProblem(
                upload_id=u.id, filename=u.filename, status=u.status, error=u.error, created_at=u.created_at
            )
            for u in failed
        ],
        corrupt_videos=[
            VideoProblem(video_id=v.id, filename=v.original_filename, error=v.error) for v in corrupt
        ],
        active_uploads=active or 0,
    )


@router.post("", response_model=SessionDetail, status_code=status.HTTP_201_CREATED)
def create_session(body: SessionCreate, db: DbSession, user: Writer) -> SessionDetail:
    _validate_refs(db, body.operator_id, body.device_id)
    _validate_times(body.started_at, body.ended_at)
    if body.name:
        if db.scalar(select(CaptureSession.id).where(CaptureSession.name == body.name)):
            raise HTTPException(status.HTTP_409_CONFLICT, f"{body.name} already exists")
        name = body.name
    else:
        day = body.capture_date or (
            body.started_at.astimezone(UTC).date() if body.started_at else datetime.now(UTC).date()
        )
        name = allocate_session_name(db, day)
    session = CaptureSession(name=name, **body.model_dump(exclude={"name", "capture_date"}))
    db.add(session)
    db.flush()
    record_event(
        db,
        "session.created",
        f"Session created: {name}",
        entity_type="session",
        entity_id=session.id,
        actor_id=user.id,
    )
    db.commit()
    return _detail(db, session.id)


@router.get("/{session_id}", response_model=SessionDetail)
def get_session(session_id: uuid.UUID, db: DbSession, _: CurrentUser) -> SessionDetail:
    return _detail(db, session_id)


@router.patch("/{session_id}", response_model=SessionDetail)
def update_session(session_id: uuid.UUID, body: SessionUpdate, db: DbSession, user: Writer) -> SessionDetail:
    session = db.get(CaptureSession, session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    changes = body.model_dump(exclude_unset=True)
    _validate_refs(db, changes.get("operator_id"), changes.get("device_id"))
    _validate_times(changes.get("started_at", session.started_at), changes.get("ended_at", session.ended_at))
    for key, value in changes.items():
        setattr(session, key, {} if key == "capture_conditions" and value is None else value)
    if changes:
        record_event(db, "session.updated", f"Session updated: {session.name}", entity_type="session",
                     entity_id=session.id, actor_id=user.id, data={"fields": sorted(changes)})  # fmt: skip
    db.commit()
    return _detail(db, session_id)


def dataset_ref(dataset: Dataset) -> Ref:
    return Ref(id=dataset.id, name=dataset.name)
