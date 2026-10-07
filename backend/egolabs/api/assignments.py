"""The Annotation Queue: sessions and videos assigned to annotators."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import aliased

from egolabs.api.annotations import user_ref
from egolabs.api.deps import CurrentUser, DbSession, Lead
from egolabs.events import record_event
from egolabs.models import (
    Annotation,
    AnnotationAssignment,
    AnnotationSource,
    AssignmentStatus,
    CaptureSession,
    Role,
    User,
    Video,
)
from egolabs.schemas import Page
from egolabs.schemas.annotation import (
    AssignableUser,
    AssignmentCreate,
    AssignmentProgress,
    AssignmentRead,
    AssignmentUpdate,
)
from egolabs.schemas.catalog import Ref

router = APIRouter(tags=["assignments"])

# Admins and reviewers hand out work; anyone who annotates can receive it.
ASSIGNABLE_ROLES = (Role.admin, Role.annotator, Role.reviewer)


def _progress(db: DbSession, rows: list[AnnotationAssignment]) -> dict[uuid.UUID, AssignmentProgress]:
    """Videos per assignment, and how many of them have at least one live human annotation."""
    human = exists().where(
        Annotation.video_id == Video.id,
        Annotation.source != AnnotationSource.auto,
        Annotation.deleted_at.is_(None),
    )
    out: dict[uuid.UUID, AssignmentProgress] = {}
    session_ids = {r.session_id for r in rows if r.session_id}
    per_session: dict[uuid.UUID, tuple[int, int]] = {}
    if session_ids:
        stmt = (
            select(Video.session_id, func.count(), func.count().filter(human))
            .where(Video.session_id.in_(session_ids))
            .group_by(Video.session_id)
        )
        per_session = {sid: (int(n), int(done)) for sid, n, done in db.execute(stmt).all()}
    video_ids = {r.video_id for r in rows if r.video_id}
    annotated_videos = (
        set(db.scalars(select(Video.id).where(Video.id.in_(video_ids), human)).all()) if video_ids else set()
    )
    for r in rows:
        if r.session_id:
            n, done = per_session.get(r.session_id, (0, 0))
            out[r.id] = AssignmentProgress(videos=n, annotated=done)
        else:
            out[r.id] = AssignmentProgress(videos=1, annotated=int(r.video_id in annotated_videos))
    return out


def _read_many(db: DbSession, rows: list[AnnotationAssignment]) -> list[AssignmentRead]:
    if not rows:
        return []
    user_ids = {r.assignee_id for r in rows} | {r.assigned_by for r in rows if r.assigned_by}
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(user_ids))).all()}
    session_ids = {r.session_id for r in rows if r.session_id}
    video_ids = {r.video_id for r in rows if r.video_id}
    sessions: dict[uuid.UUID, str] = {}
    videos: dict[uuid.UUID, str] = {}
    if session_ids:
        stmt = select(CaptureSession.id, CaptureSession.name).where(CaptureSession.id.in_(session_ids))
        sessions = {sid: name for sid, name in db.execute(stmt).all()}
    if video_ids:
        stmt = select(Video.id, Video.original_filename).where(Video.id.in_(video_ids))
        videos = {vid: name for vid, name in db.execute(stmt).all()}
    progress = _progress(db, rows)
    out = []
    for r in rows:
        assignee = user_ref(users.get(r.assignee_id))
        assert assignee is not None
        out.append(
            AssignmentRead(
                id=r.id,
                target_type="session" if r.session_id else "video",
                session=Ref(id=r.session_id, name=sessions[r.session_id]) if r.session_id else None,
                video=Ref(id=r.video_id, name=videos[r.video_id]) if r.video_id else None,
                assignee=assignee,
                assigned_by=user_ref(users.get(r.assigned_by)) if r.assigned_by else None,
                status=r.status,
                note=r.note,
                progress=progress[r.id],
                created_at=r.created_at,
                updated_at=r.updated_at,
                completed_at=r.completed_at,
            )
        )
    return out


def _get(db: DbSession, assignment_id: uuid.UUID) -> AnnotationAssignment:
    row = db.get(AnnotationAssignment, assignment_id, with_for_update=True)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")
    return row


def _assignee(db: DbSession, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None or not user.is_active or user.role not in ASSIGNABLE_ROLES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Assignee must be an active annotator, reviewer, or admin"
        )
    return user


@router.get("/users/assignable", response_model=list[AssignableUser], tags=["users"])
def assignable_users(db: DbSession, _: CurrentUser) -> list[AssignableUser]:
    rows = db.scalars(
        select(User)
        .where(User.is_active.is_(True), User.role.in_(ASSIGNABLE_ROLES))
        .order_by(func.coalesce(User.name, User.email))
        .limit(500)
    ).all()
    return [AssignableUser(id=u.id, name=u.name or u.email, email=u.email, role=u.role) for u in rows]


@router.get("/assignments", response_model=Page[AssignmentRead])
def list_assignments(
    db: DbSession,
    user: CurrentUser,
    mine: bool = False,
    assignee_id: uuid.UUID | None = None,
    status_: Annotated[list[AssignmentStatus] | None, Query(alias="status")] = None,
    session_id: uuid.UUID | None = None,
    video_id: uuid.UUID | None = Query(default=None, description="Assignments covering this video"),
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[AssignmentRead]:
    stmt = select(AnnotationAssignment)
    if mine:
        stmt = stmt.where(AnnotationAssignment.assignee_id == user.id)
    if assignee_id:
        stmt = stmt.where(AnnotationAssignment.assignee_id == assignee_id)
    if status_:
        stmt = stmt.where(AnnotationAssignment.status.in_(status_))
    if session_id:
        stmt = stmt.where(AnnotationAssignment.session_id == session_id)
    if video_id:
        v = aliased(Video)
        in_session = exists().where(v.id == video_id, v.session_id == AnnotationAssignment.session_id)
        stmt = stmt.where(or_(AnnotationAssignment.video_id == video_id, in_session))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    # Open work first, then newest.
    open_first = AnnotationAssignment.status == AssignmentStatus.done
    rows = list(
        db.scalars(
            stmt.order_by(open_first, AnnotationAssignment.created_at.desc(), AnnotationAssignment.id)
            .limit(limit)
            .offset(offset)
        ).all()
    )
    return Page[AssignmentRead](items=_read_many(db, rows), total=total, limit=limit, offset=offset)


@router.post("/assignments", response_model=AssignmentRead, status_code=201)
def create_assignment(body: AssignmentCreate, db: DbSession, lead: Lead) -> AssignmentRead:
    assignee = _assignee(db, body.assignee_id)
    if body.session_id:
        session = db.get(CaptureSession, body.session_id)
        if session is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Session not found")
        target, target_name = AnnotationAssignment.session_id == body.session_id, session.name
    else:
        video = db.get(Video, body.video_id)
        if video is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Video not found")
        target, target_name = AnnotationAssignment.video_id == body.video_id, video.original_filename
    duplicate = db.scalar(
        select(AnnotationAssignment.id).where(
            target,
            AnnotationAssignment.assignee_id == assignee.id,
            AnnotationAssignment.status != AssignmentStatus.done,
        )
    )
    if duplicate:
        raise HTTPException(status.HTTP_409_CONFLICT, "This is already in their queue")
    row = AnnotationAssignment(
        session_id=body.session_id, video_id=body.video_id, assignee_id=assignee.id, assigned_by=lead.id,
        note=body.note,
    )  # fmt: skip
    db.add(row)
    db.flush()
    record_event(db, "assignment.created", f"{target_name} assigned to {assignee.name or assignee.email}",
                 entity_type="assignment", entity_id=row.id, actor_id=lead.id,
                 data={"assignee_id": str(assignee.id)})  # fmt: skip
    db.commit()
    return _read_many(db, [row])[0]


@router.patch("/assignments/{assignment_id}", response_model=AssignmentRead)
def update_assignment(
    assignment_id: uuid.UUID, body: AssignmentUpdate, db: DbSession, user: CurrentUser
) -> AssignmentRead:
    row = _get(db, assignment_id)
    is_lead = user.role in (Role.admin, Role.reviewer)
    if not is_lead and row.assignee_id != user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the assignee or a reviewer/admin can change this"
        )
    if not is_lead and ({"assignee_id", "note"} & body.model_fields_set):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only a reviewer or admin can reassign or edit the note"
        )
    changed: dict[str, object] = {}
    if body.status is not None and body.status != row.status:
        changed["status"] = {"from": row.status.value, "to": body.status.value}
        row.status = body.status
        row.completed_at = datetime.now(UTC) if body.status == AssignmentStatus.done else None
    if body.assignee_id is not None and body.assignee_id != row.assignee_id:
        _assignee(db, body.assignee_id)
        changed["assignee_id"] = {"from": str(row.assignee_id), "to": str(body.assignee_id)}
        row.assignee_id = body.assignee_id
    if "note" in body.model_fields_set and body.note != row.note:
        changed["note"] = True
        row.note = body.note
    if changed:
        row.updated_at = datetime.now(UTC)
        record_event(db, "assignment.updated", "Assignment updated", entity_type="assignment",
                     entity_id=row.id, actor_id=user.id, data=changed)  # fmt: skip
    db.commit()
    return _read_many(db, [row])[0]


@router.delete("/assignments/{assignment_id}", status_code=204)
def delete_assignment(assignment_id: uuid.UUID, db: DbSession, lead: Lead) -> None:
    row = _get(db, assignment_id)
    record_event(db, "assignment.removed", "Assignment removed", entity_type="assignment", entity_id=row.id,
                 actor_id=lead.id)  # fmt: skip
    db.delete(row)
    db.commit()
