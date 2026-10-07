"""cv runs and hand tracks

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-23 16:27:33.099702
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cv_runs",
        sa.Column("video_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("model_version_id", sa.UUID(), nullable=True),
        sa.Column("job_id", sa.UUID(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "succeeded",
                "failed",
                name="cv_run_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="queued",
            nullable=False,
        ),
        sa.Column("adapter", sa.String(length=300), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("stride", sa.Integer(), server_default="1", nullable=False),
        sa.Column("frames_total", sa.Integer(), nullable=True),
        sa.Column("frames_processed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("frames_with_hands", sa.Integer(), server_default="0", nullable=False),
        sa.Column("detections", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tracks", sa.Integer(), server_default="0", nullable=False),
        sa.Column("missing_detections", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tracking_failures", sa.Integer(), server_default="0", nullable=False),
        sa.Column("mean_confidence", sa.Float(), nullable=True),
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("stats", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("stride >= 1", name=op.f("ck_cv_runs_stride_positive")),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_cv_runs_created_by_users"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name=op.f("fk_cv_runs_job_id_jobs"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["model_version_id"],
            ["model_versions.id"],
            name=op.f("fk_cv_runs_model_version_id_model_versions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["video_id"], ["videos.id"], name=op.f("fk_cv_runs_video_id_videos"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cv_runs")),
    )
    op.create_index(op.f("ix_cv_runs_model_version_id"), "cv_runs", ["model_version_id"], unique=False)
    op.create_index(
        "ix_cv_runs_video_id_kind_created_at", "cv_runs", ["video_id", "kind", "created_at"], unique=False
    )
    op.create_table(
        "hand_tracks",
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("model_version_id", sa.UUID(), nullable=False),
        sa.Column("track_id", sa.Integer(), nullable=False),
        sa.Column("handedness", sa.String(length=8), nullable=False),
        sa.Column("first_frame", sa.Integer(), nullable=False),
        sa.Column("last_frame", sa.Integer(), nullable=False),
        sa.Column("frames_detected", sa.Integer(), nullable=False),
        sa.Column("missing_detections", sa.Integer(), server_default="0", nullable=False),
        sa.Column("mean_confidence", sa.Float(), nullable=False),
        sa.Column("path_length_px", sa.Float(), nullable=False),
        sa.Column("mean_speed_px_s", sa.Float(), nullable=False),
        sa.Column("peak_speed_px_s", sa.Float(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("last_frame >= first_frame", name=op.f("ck_hand_tracks_frame_range")),
        sa.ForeignKeyConstraint(
            ["model_version_id"],
            ["model_versions.id"],
            name=op.f("fk_hand_tracks_model_version_id_model_versions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["cv_runs.id"], name=op.f("fk_hand_tracks_run_id_cv_runs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hand_tracks")),
        sa.UniqueConstraint("run_id", "track_id", name=op.f("uq_hand_tracks_run_id_track_id")),
    )
    op.create_index(op.f("ix_hand_tracks_run_id"), "hand_tracks", ["run_id"], unique=False)
    op.add_column("annotations", sa.Column("cv_run_id", sa.UUID(), nullable=True))
    op.create_index(op.f("ix_annotations_cv_run_id"), "annotations", ["cv_run_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_annotations_cv_run_id_cv_runs"),
        "annotations",
        "cv_runs",
        ["cv_run_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_annotations_cv_run_id_cv_runs"), "annotations", type_="foreignkey")
    op.drop_index(op.f("ix_annotations_cv_run_id"), table_name="annotations")
    op.drop_column("annotations", "cv_run_id")
    op.drop_index(op.f("ix_hand_tracks_run_id"), table_name="hand_tracks")
    op.drop_table("hand_tracks")
    op.drop_index("ix_cv_runs_video_id_kind_created_at", table_name="cv_runs")
    op.drop_index(op.f("ix_cv_runs_model_version_id"), table_name="cv_runs")
    op.drop_table("cv_runs")
