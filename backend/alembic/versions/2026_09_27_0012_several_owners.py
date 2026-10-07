"""several owners

`OWNER_EMAIL` can name several owners (comma-separated), all admins, none changeable from the app. The
one-owner index goes; every listed account becomes an owner, and owners no longer listed lose it.

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-27 06:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _owner_emails() -> list[str]:
    from egolabs.config import get_settings

    return [e.strip().lower() for e in (get_settings().owner_email or "").split(",") if e.strip()]


def upgrade() -> None:
    op.drop_index("uq_users_owner", table_name="users")
    emails = _owner_emails()
    if emails:
        op.execute(
            sa.text(
                "UPDATE users SET is_owner = true, role = 'admin', is_active = true WHERE lower(email) = ANY(:e)"
            ).bindparams(e=emails)
        )
        op.execute(
            sa.text(
                "UPDATE users SET is_owner = false, role = 'pending' WHERE is_owner AND lower(email) <> ALL(:e)"
            ).bindparams(e=emails)
        )


def downgrade() -> None:
    # Back to one owner: keep the earliest.
    op.execute(
        "UPDATE users SET is_owner = false, role = 'pending' WHERE is_owner AND id <> "
        "(SELECT id FROM users WHERE is_owner ORDER BY created_at, id LIMIT 1)"
    )
    op.create_index(
        "uq_users_owner", "users", ["is_owner"], unique=True, postgresql_where=sa.text("is_owner")
    )
