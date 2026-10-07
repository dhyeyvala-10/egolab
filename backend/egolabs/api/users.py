"""People and what they do, for the owner (the only admin): give or take away access, block accounts, and see
every sign-in and every action with who did it."""

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from egolabs.api.deps import AdminUser, DbSession
from egolabs.events import record_event
from egolabs.models import Event, Role, SignIn, User
from egolabs.schemas import AdminActivity, Page, SignInRead, UserRead, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=Page[UserRead])
def list_users(
    db: DbSession,
    _: AdminUser,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[UserRead]:
    """Everyone who has signed in: the owner first, then people waiting for access, then the rest."""
    total = db.scalar(select(func.count()).select_from(User)) or 0
    waiting = (User.role == Role.pending) & User.is_active
    rows = db.scalars(
        select(User)
        .order_by(User.is_owner.desc(), waiting.desc(), User.created_at, User.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return Page[UserRead](
        items=[UserRead.model_validate(u) for u in rows], total=total, limit=limit, offset=offset
    )


@router.patch("/{user_id}", response_model=UserRead)
def update_user(user_id: uuid.UUID, body: UserUpdate, db: DbSession, admin: AdminUser) -> User:
    """Give someone a role (or take their access away with `pending`), or block them. Nobody can be made
    admin, and the owner can't be changed."""
    user = db.get(User, user_id, with_for_update=True)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if user.is_owner:
        raise HTTPException(status.HTTP_409_CONFLICT, "The owner's account can't be changed")

    changes: dict[str, object] = {}
    if body.role is not None and body.role != user.role.value:
        changes["role"] = {"from": user.role.value, "to": body.role}
        user.role = Role(body.role)
    if body.is_active is not None and body.is_active != user.is_active:
        changes["is_active"] = {"from": user.is_active, "to": body.is_active}
        user.is_active = body.is_active

    if changes:
        what = []
        if "role" in changes:
            what.append("no access" if body.role == "pending" else f"role {body.role}")
        if "is_active" in changes:
            what.append("unblocked" if body.is_active else "blocked")
        record_event(
            db,
            "user.updated",
            f"{user.name or user.email}: {', '.join(what)}",
            entity_type="user",
            entity_id=user.id,
            actor_id=admin.id,
            data=changes,
        )
    db.commit()
    return user


@router.get("/sign-ins", response_model=Page[SignInRead])
def list_sign_ins(
    db: DbSession,
    _: AdminUser,
    user_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[SignInRead]:
    """Every sign-in, newest first, with the address and browser it came from."""
    stmt = select(SignIn, User).join(User, User.id == SignIn.user_id)
    if user_id:
        stmt = stmt.where(SignIn.user_id == user_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(stmt.order_by(SignIn.created_at.desc(), SignIn.id).limit(limit).offset(offset)).all()
    items = [
        SignInRead(
            id=s.id,
            user_id=s.user_id,
            user_email=u.email,
            user_name=u.name,
            method=s.method,
            ip=s.ip,
            user_agent=s.user_agent,
            created_at=s.created_at,
        )  # fmt: skip
        for s, u in rows
    ]
    return Page[SignInRead](items=items, total=total, limit=limit, offset=offset)


@router.get("/activity", response_model=Page[AdminActivity])
def list_activity(
    db: DbSession,
    _: AdminUser,
    user_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[AdminActivity]:
    """Everything that happened, newest first, with who did it (system work, like processing, has nobody)."""
    stmt = select(Event, User).outerjoin(User, User.id == Event.actor_id)
    if user_id:
        stmt = stmt.where(Event.actor_id == user_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(stmt.order_by(Event.id.desc()).limit(limit).offset(offset)).all()
    items = [
        AdminActivity(
            id=e.id,
            type=e.type,
            message=e.message,
            entity_type=e.entity_type,
            entity_id=e.entity_id,
            actor_id=e.actor_id,
            actor_email=u.email if u else None,
            actor_name=u.name if u else None,
            created_at=e.created_at,
        )  # fmt: skip
        for e, u in rows
    ]
    return Page[AdminActivity](items=items, total=total, limit=limit, offset=offset)
