"""google sign-in

People sign in with Google: accounts get Google's stable id (`google_sub`, unique), and a password is no
longer required (Google accounts have none).

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-25 02:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("google_sub", sa.String(length=255), nullable=True))
    op.create_unique_constraint(op.f("uq_users_google_sub"), "users", ["google_sub"])
    op.alter_column("users", "password_hash", existing_type=sa.String(length=255), nullable=True)


def downgrade() -> None:
    # Accounts made with Google have no password; they can't sign in with one after a downgrade.
    op.execute("UPDATE users SET password_hash = '!' WHERE password_hash IS NULL")
    op.alter_column("users", "password_hash", existing_type=sa.String(length=255), nullable=False)
    op.drop_constraint(op.f("uq_users_google_sub"), "users", type_="unique")
    op.drop_column("users", "google_sub")
