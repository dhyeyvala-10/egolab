"""owner, access, sign-ins, limits and approvals

- One owner (`users.is_owner`), the only admin. `OWNER_EMAIL` names them; without it, the earliest admin.
  Any other admin loses admin.
- New accounts have no access (role `pending`) until the owner gives them a role. Accounts that were made
  viewers automatically become `pending` too: nobody chose to give them access.
- Every sign-in is kept (`sign_ins`), and accounts remember when they last signed in and were last seen.
- The owner's settings (`app_settings`): upload size limit, video length limit, who may start processing.
- Uploads over the size limit wait for the owner (`awaiting_approval`, then `uploading` or `rejected`);
  videos over the length limit are held (`videos.processing_hold`) until the owner allows them.

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-25 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLES = "'admin', 'annotator', 'reviewer', 'viewer'"
UPLOAD_STATUSES = "'uploading', 'processing', 'processed', 'duplicate', 'failed', 'aborted'"


def _owner_email() -> str | None:
    """The first of OWNER_EMAIL's emails (0011 allows one owner; 0012 allows the rest)."""
    from egolabs.config import get_settings

    emails = [e.strip().lower() for e in (get_settings().owner_email or "").split(",") if e.strip()]
    return emails[0] if emails else None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_users_user_role"), "users", type_="check")
    op.create_check_constraint("user_role", "users", f"role IN ({ROLES}, 'pending')")
    op.add_column("users", sa.Column("is_owner", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("users", sa.Column("last_sign_in_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "uq_users_owner", "users", ["is_owner"], unique=True, postgresql_where=sa.text("is_owner")
    )

    owner = _owner_email()
    if owner:
        op.execute(
            sa.text(
                "UPDATE users SET is_owner = true, role = 'admin', is_active = true WHERE lower(email) = :e"
            ).bindparams(e=owner)
        )
    else:
        op.execute(
            "UPDATE users SET is_owner = true WHERE id = "
            "(SELECT id FROM users WHERE role = 'admin' ORDER BY created_at, id LIMIT 1)"
        )
    op.execute("UPDATE users SET role = 'pending' WHERE NOT is_owner AND role IN ('admin', 'viewer')")

    op.create_table(
        "sign_ins",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("method", sa.String(length=16), nullable=False),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_sign_ins_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sign_ins")),
    )
    op.create_index("ix_sign_ins_user_created", "sign_ins", ["user_id", "created_at"])

    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["users.id"], name=op.f("fk_app_settings_updated_by_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_app_settings")),
    )

    op.drop_constraint(op.f("ck_uploads_upload_status"), "uploads", type_="check")
    op.create_check_constraint(
        "upload_status", "uploads", f"status IN ({UPLOAD_STATUSES}, 'awaiting_approval', 'rejected')"
    )
    op.add_column("uploads", sa.Column("approval_reason", sa.Text(), nullable=True))
    op.add_column("uploads", sa.Column("reviewed_by", sa.UUID(), nullable=True))
    op.add_column("uploads", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        op.f("fk_uploads_reviewed_by_users"), "uploads", "users", ["reviewed_by"], ["id"], ondelete="SET NULL"
    )

    op.add_column("videos", sa.Column("processing_hold", sa.String(length=32), nullable=True))
    op.add_column("videos", sa.Column("hold_reason", sa.Text(), nullable=True))
    op.create_check_constraint(
        "processing_hold", "videos", "processing_hold IN ('held', 'allowed', 'rejected')"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_videos_processing_hold"), "videos", type_="check")
    op.drop_column("videos", "hold_reason")
    op.drop_column("videos", "processing_hold")

    op.drop_constraint(op.f("fk_uploads_reviewed_by_users"), "uploads", type_="foreignkey")
    op.drop_column("uploads", "reviewed_at")
    op.drop_column("uploads", "reviewed_by")
    op.drop_column("uploads", "approval_reason")
    op.execute("UPDATE uploads SET status = 'aborted' WHERE status IN ('awaiting_approval', 'rejected')")
    op.drop_constraint(op.f("ck_uploads_upload_status"), "uploads", type_="check")
    op.create_check_constraint("upload_status", "uploads", f"status IN ({UPLOAD_STATUSES})")

    op.drop_table("app_settings")
    op.drop_index("ix_sign_ins_user_created", table_name="sign_ins")
    op.drop_table("sign_ins")

    op.execute("UPDATE users SET role = 'viewer' WHERE role = 'pending'")
    op.drop_index("uq_users_owner", table_name="users")
    op.drop_column("users", "last_seen_at")
    op.drop_column("users", "last_sign_in_at")
    op.drop_column("users", "is_owner")
    op.drop_constraint(op.f("ck_users_user_role"), "users", type_="check")
    op.create_check_constraint("user_role", "users", f"role IN ({ROLES})")
