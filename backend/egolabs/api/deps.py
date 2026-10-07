from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import update
from sqlalchemy.orm import Session

from egolabs import app_settings, owner
from egolabs.db import get_db
from egolabs.models import Role, User
from egolabs.security import decode_access_token

DbSession = Annotated[Session, Depends(get_db)]

_bearer = HTTPBearer(auto_error=False)
SEEN_EVERY = timedelta(minutes=1)
WAITING_FOR_ACCESS = "Your account is waiting for the admin to give you access"


def get_signed_in_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    """Any active account, including one still waiting for access (for /auth/me only)."""
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED, "Not authenticated", headers={"WWW-Authenticate": "Bearer"}
    )
    if credentials is None:
        raise unauthorized
    user_id = decode_access_token(credentials.credentials)
    if user_id is None:
        raise unauthorized
    user = db.get(User, user_id)
    if user is None:
        raise unauthorized
    if owner.sync(db, user):
        db.commit()
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is deactivated")
    now = datetime.now(UTC)
    if user.last_seen_at is None or now - user.last_seen_at >= SEEN_EVERY:
        db.execute(update(User).where(User.id == user.id).values(last_seen_at=now))
        db.commit()
    return user


SignedInUser = Annotated[User, Depends(get_signed_in_user)]


def get_current_user(user: SignedInUser) -> User:
    if user.role == Role.pending:
        raise HTTPException(status.HTTP_403_FORBIDDEN, WAITING_FOR_ACCESS)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: Role) -> Callable[[User], User]:
    def dependency(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, f"Requires role: {', '.join(r.value for r in roles)}"
            )
        return user

    return dependency


AdminUser = Annotated[User, Depends(require_roles(Role.admin))]

# Roles that can create and change data (viewers are read-only).
Writer = Annotated[User, Depends(require_roles(Role.admin, Role.annotator, Role.reviewer))]

# Leads run the annotation work: assign it, and define the movement taxonomy.
Lead = Annotated[User, Depends(require_roles(Role.admin, Role.reviewer))]


def get_processor(user: Writer, db: DbSession) -> User:
    """Starting processing (and changing what processes): the owner, and editors when the owner allows it."""
    if user.role != Role.admin and app_settings.get(db).processing_by == "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the admin can start processing")
    return user


# Starts or changes processing: pipelines and their runs and schedules, CV runs, auto annotation, dataset
# versions and exports. Who may is the owner's setting (Settings → Limits).
Processor = Annotated[User, Depends(get_processor)]
