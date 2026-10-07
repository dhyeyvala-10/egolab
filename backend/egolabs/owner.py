"""The owners: the admins. `OWNER_EMAIL` names them, one or more emails separated by commas (else the first
account made is the only owner).

Nobody else can be made admin, and nobody can change an owner from the app: owners are added or removed only
in `OWNER_EMAIL`. Everyone else starts with no access (`Role.pending`) and gets what an owner gives them.
"""

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from egolabs.config import get_settings
from egolabs.models import Role, User


def owner_emails() -> frozenset[str]:
    raw = get_settings().owner_email or ""
    return frozenset(e.strip().lower() for e in raw.split(",") if e.strip())


def is_owner_email(email: str) -> bool:
    return email.strip().lower() in owner_emails()


def new_account_is_owner(db: Session, email: str) -> bool:
    """Whether an account being made now is an owner (caller holds the registration lock)."""
    if owner_emails():
        return is_owner_email(email)
    return (
        db.scalar(select(User.id).where(User.is_owner)) is None
        and db.scalar(select(User.id).limit(1)) is None
    )


def sync(db: Session, user: User) -> bool:
    """Make `user`'s owner status and role follow the rule (owners are admins; nobody else is). Returns whether
    anything changed; the caller commits."""
    owners = owner_emails()
    should_own = user.email.strip().lower() in owners if owners else user.is_owner
    changed = False
    if should_own:
        if not user.is_owner:
            if owners:  # OWNER_EMAIL changed: anyone taken out of it keeps nothing of it
                db.execute(
                    update(User)
                    .where(User.is_owner, User.id != user.id, func.lower(User.email).not_in(owners))
                    .values(is_owner=False, role=Role.pending)
                )
            user.is_owner, changed = True, True
        if user.role != Role.admin or not user.is_active:
            user.role, user.is_active, changed = Role.admin, True, True
    else:
        if user.is_owner:
            user.is_owner, changed = False, True
        if user.role == Role.admin:
            user.role, changed = Role.pending, True
    return changed
