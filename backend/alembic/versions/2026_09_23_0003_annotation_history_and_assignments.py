"""annotation history and assignments

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-23 13:55:00.888820
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "annotation_assignments",
        sa.Column("session_id", sa.UUID(), nullable=True),
        sa.Column("video_id", sa.UUID(), nullable=True),
        sa.Column("assignee_id", sa.UUID(), nullable=False),
        sa.Column("assigned_by", sa.UUID(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "todo",
                "in_progress",
                "done",
                name="assignment_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="todo",
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "num_nonnulls(session_id, video_id) = 1", name=op.f("ck_annotation_assignments_one_target")
        ),
        sa.ForeignKeyConstraint(
            ["assigned_by"],
            ["users.id"],
            name=op.f("fk_annotation_assignments_assigned_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["assignee_id"],
            ["users.id"],
            name=op.f("fk_annotation_assignments_assignee_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name=op.f("fk_annotation_assignments_session_id_sessions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["video_id"],
            ["videos.id"],
            name=op.f("fk_annotation_assignments_video_id_videos"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_annotation_assignments")),
    )
    op.create_index(
        "ix_annotation_assignments_assignee_id_status",
        "annotation_assignments",
        ["assignee_id", "status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_annotation_assignments_session_id"), "annotation_assignments", ["session_id"], unique=False
    )
    op.create_index(
        op.f("ix_annotation_assignments_video_id"), "annotation_assignments", ["video_id"], unique=False
    )
    op.create_table(
        "annotation_revisions",
        sa.Column("annotation_id", sa.UUID(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "action",
            sa.Enum(
                "created",
                "updated",
                "flagged",
                "unflagged",
                "deleted",
                "restored",
                "superseded",
                name="revision_action",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("changes", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("related_annotation_id", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name=op.f("fk_annotation_revisions_actor_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["annotation_id"],
            ["annotations.id"],
            name=op.f("fk_annotation_revisions_annotation_id_annotations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["related_annotation_id"],
            ["annotations.id"],
            name=op.f("fk_annotation_revisions_related_annotation_id_annotations"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_annotation_revisions")),
        sa.UniqueConstraint(
            "annotation_id", "revision", name=op.f("uq_annotation_revisions_annotation_id_revision")
        ),
    )
    op.add_column(
        "annotations",
        sa.Column(
            "category",
            sa.Enum(
                "general",
                "hand",
                "finger",
                "object",
                "movement",
                name="annotation_category",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="general",
            nullable=False,
        ),
    )
    op.add_column(
        "annotations",
        sa.Column("needs_review", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("annotations", sa.Column("revision", sa.Integer(), server_default="1", nullable=False))
    op.add_column("annotations", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("annotations", sa.Column("updated_by", sa.UUID(), nullable=True))
    op.add_column("annotations", sa.Column("deleted_by", sa.UUID(), nullable=True))
    op.add_column("annotations", sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        op.f("fk_annotations_updated_by_users"),
        "annotations",
        "users",
        ["updated_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_annotations_deleted_by_users"),
        "annotations",
        "users",
        ["deleted_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        op.f("ck_annotations_frame_start_non_negative"), "annotations", "frame_start >= 0"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_annotations_frame_start_non_negative"), "annotations", type_="check")
    op.drop_constraint(op.f("fk_annotations_deleted_by_users"), "annotations", type_="foreignkey")
    op.drop_constraint(op.f("fk_annotations_updated_by_users"), "annotations", type_="foreignkey")
    op.drop_column("annotations", "superseded_at")
    op.drop_column("annotations", "deleted_by")
    op.drop_column("annotations", "updated_by")
    op.drop_column("annotations", "updated_at")
    op.drop_column("annotations", "revision")
    op.drop_column("annotations", "needs_review")
    op.drop_column("annotations", "category")
    op.drop_table("annotation_revisions")
    op.drop_index(op.f("ix_annotation_assignments_video_id"), table_name="annotation_assignments")
    op.drop_index(op.f("ix_annotation_assignments_session_id"), table_name="annotation_assignments")
    op.drop_index("ix_annotation_assignments_assignee_id_status", table_name="annotation_assignments")
    op.drop_table("annotation_assignments")
