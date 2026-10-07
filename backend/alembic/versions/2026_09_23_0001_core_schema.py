"""core schema

Revision ID: 0001
Revises:
Create Date: 2026-09-23 11:24:07.753524
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "devices",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=100), nullable=True),
        sa.Column("serial", sa.String(length=200), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_devices")),
        sa.UniqueConstraint("name", name=op.f("uq_devices_name")),
    )
    op.create_table(
        "model_versions",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("version", sa.String(length=100), nullable=False),
        sa.Column("kind", sa.String(length=100), nullable=False),
        sa.Column("adapter", sa.String(length=300), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("keypoint_schema", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_versions")),
        sa.UniqueConstraint("name", "version", name=op.f("uq_model_versions_name_version")),
    )
    op.create_table(
        "operators",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("external_id", sa.String(length=200), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_operators")),
        sa.UniqueConstraint("external_id", name=op.f("uq_operators_external_id")),
    )
    op.create_table(
        "users",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "admin",
                "annotator",
                "reviewer",
                "viewer",
                name="user_role",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_table(
        "datasets",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_datasets_created_by_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_datasets")),
        sa.UniqueConstraint("name", name=op.f("uq_datasets_name")),
    )
    op.create_table(
        "events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("type", sa.String(length=100), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=True),
        sa.Column("entity_id", sa.UUID(), nullable=True),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name=op.f("fk_events_actor_id_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_events")),
    )
    op.create_index("ix_events_created_at", "events", ["created_at"], unique=False)
    op.create_index("ix_events_entity", "events", ["entity_type", "entity_id"], unique=False)
    op.create_index(op.f("ix_events_type"), "events", ["type"], unique=False)
    op.create_table(
        "jobs",
        sa.Column("type", sa.String(length=100), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "succeeded",
                "failed",
                "cancelled",
                "retrying",
                name="job_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("parent_job_id", sa.UUID(), nullable=True),
        sa.Column("celery_task_id", sa.String(length=255), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_jobs_created_by_users"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["parent_job_id"], ["jobs.id"], name=op.f("fk_jobs_parent_job_id_jobs"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
    )
    op.create_index(op.f("ix_jobs_celery_task_id"), "jobs", ["celery_task_id"], unique=False)
    op.create_index("ix_jobs_status_created_at", "jobs", ["status", "created_at"], unique=False)
    op.create_index(op.f("ix_jobs_type"), "jobs", ["type"], unique=False)
    op.create_table(
        "sessions",
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("operator_id", sa.UUID(), nullable=True),
        sa.Column("device_id", sa.UUID(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("environment", sa.String(length=200), nullable=True),
        sa.Column("task", sa.String(length=200), nullable=True),
        sa.Column("location", sa.String(length=200), nullable=True),
        sa.Column(
            "capture_conditions", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "name ~ '^SESSION_[0-9]{4}_[0-9]{2}_[0-9]{2}_[0-9]{3}$'", name=op.f("ck_sessions_name_format")
        ),
        sa.ForeignKeyConstraint(
            ["device_id"], ["devices.id"], name=op.f("fk_sessions_device_id_devices"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["operator_id"],
            ["operators.id"],
            name=op.f("fk_sessions_operator_id_operators"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.UniqueConstraint("name", name=op.f("uq_sessions_name")),
    )
    op.create_index(op.f("ix_sessions_device_id"), "sessions", ["device_id"], unique=False)
    op.create_index(op.f("ix_sessions_operator_id"), "sessions", ["operator_id"], unique=False)
    op.create_table(
        "dataset_sessions",
        sa.Column("dataset_id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.id"],
            name=op.f("fk_dataset_sessions_dataset_id_datasets"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name=op.f("fk_dataset_sessions_session_id_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("dataset_id", "session_id", name=op.f("pk_dataset_sessions")),
    )
    op.create_table(
        "job_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "level",
            sa.Enum(
                "debug",
                "info",
                "warning",
                "error",
                name="log_level",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name=op.f("fk_job_logs_job_id_jobs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_logs")),
    )
    op.create_index("ix_job_logs_job_id_id", "job_logs", ["job_id", "id"], unique=False)
    op.create_table(
        "lineage_edges",
        sa.Column("parent_type", sa.String(length=64), nullable=False),
        sa.Column("parent_id", sa.UUID(), nullable=False),
        sa.Column("child_type", sa.String(length=64), nullable=False),
        sa.Column("child_id", sa.UUID(), nullable=False),
        sa.Column("relation", sa.String(length=64), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "NOT (parent_type = child_type AND parent_id = child_id)",
            name=op.f("ck_lineage_edges_no_self_edge"),
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name=op.f("fk_lineage_edges_job_id_jobs"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lineage_edges")),
        sa.UniqueConstraint(
            "parent_type",
            "parent_id",
            "child_type",
            "child_id",
            "relation",
            name=op.f("uq_lineage_edges_parent_type_parent_id_child_type_child_id_relation"),
        ),
    )
    op.create_index("ix_lineage_edges_child", "lineage_edges", ["child_type", "child_id"], unique=False)
    op.create_index("ix_lineage_edges_parent", "lineage_edges", ["parent_type", "parent_id"], unique=False)
    op.create_table(
        "videos",
        sa.Column("session_id", sa.UUID(), nullable=True),
        sa.Column("original_filename", sa.String(length=1024), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "uploaded",
                "processing",
                "ready",
                "corrupt",
                name="video_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("duration_s", sa.Float(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("fps", sa.Float(), nullable=True),
        sa.Column("codec", sa.String(length=64), nullable=True),
        sa.Column("frame_count", sa.BigInteger(), nullable=True),
        sa.Column("probe", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("camera_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("proxy_key", sa.String(length=1024), nullable=True),
        sa.Column("thumbnails_key", sa.String(length=1024), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sessions.id"], name=op.f("fk_videos_session_id_sessions"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_videos")),
        sa.UniqueConstraint("sha256", name=op.f("uq_videos_sha256")),
        sa.UniqueConstraint("storage_key", name=op.f("uq_videos_storage_key")),
    )
    op.create_index(op.f("ix_videos_session_id"), "videos", ["session_id"], unique=False)
    op.create_table(
        "annotations",
        sa.Column("video_id", sa.UUID(), nullable=False),
        sa.Column(
            "type",
            sa.Enum(
                "segment",
                "bbox",
                "keypoint",
                name="annotation_type",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("frame_start", sa.Integer(), nullable=False),
        sa.Column("frame_end", sa.Integer(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column(
            "source",
            sa.Enum(
                "auto",
                "human",
                "auto_corrected",
                name="annotation_source",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("model_version_id", sa.UUID(), nullable=True),
        sa.Column("parent_annotation_id", sa.UUID(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "source <> 'auto' OR (confidence IS NOT NULL AND model_version_id IS NOT NULL)",
            name=op.f("ck_annotations_auto_has_confidence_and_model"),
        ),
        sa.CheckConstraint(
            "source <> 'auto_corrected' OR parent_annotation_id IS NOT NULL",
            name=op.f("ck_annotations_correction_has_parent"),
        ),
        sa.CheckConstraint(
            "source = 'auto' OR created_by IS NOT NULL", name=op.f("ck_annotations_human_has_author")
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name=op.f("ck_annotations_confidence_range"),
        ),
        sa.CheckConstraint("frame_end >= frame_start", name=op.f("ck_annotations_frame_range")),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_annotations_created_by_users"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["model_version_id"],
            ["model_versions.id"],
            name=op.f("fk_annotations_model_version_id_model_versions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parent_annotation_id"],
            ["annotations.id"],
            name=op.f("fk_annotations_parent_annotation_id_annotations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["video_id"], ["videos.id"], name=op.f("fk_annotations_video_id_videos"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_annotations")),
    )
    op.create_index(
        op.f("ix_annotations_model_version_id"), "annotations", ["model_version_id"], unique=False
    )
    op.create_index(
        op.f("ix_annotations_parent_annotation_id"), "annotations", ["parent_annotation_id"], unique=False
    )
    op.create_index(
        "ix_annotations_video_id_frame_start", "annotations", ["video_id", "frame_start"], unique=False
    )
    op.create_table(
        "frames",
        sa.Column("video_id", sa.UUID(), nullable=False),
        sa.Column("frame_index", sa.Integer(), nullable=False),
        sa.Column("timestamp_s", sa.Float(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("frame_index >= 0", name=op.f("ck_frames_frame_index_non_negative")),
        sa.ForeignKeyConstraint(
            ["video_id"], ["videos.id"], name=op.f("fk_frames_video_id_videos"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_frames")),
        sa.UniqueConstraint("video_id", "frame_index", name=op.f("uq_frames_video_id_frame_index")),
    )


def downgrade() -> None:
    op.drop_table("frames")
    op.drop_index("ix_annotations_video_id_frame_start", table_name="annotations")
    op.drop_index(op.f("ix_annotations_parent_annotation_id"), table_name="annotations")
    op.drop_index(op.f("ix_annotations_model_version_id"), table_name="annotations")
    op.drop_table("annotations")
    op.drop_index(op.f("ix_videos_session_id"), table_name="videos")
    op.drop_table("videos")
    op.drop_index("ix_lineage_edges_parent", table_name="lineage_edges")
    op.drop_index("ix_lineage_edges_child", table_name="lineage_edges")
    op.drop_table("lineage_edges")
    op.drop_index("ix_job_logs_job_id_id", table_name="job_logs")
    op.drop_table("job_logs")
    op.drop_table("dataset_sessions")
    op.drop_index(op.f("ix_sessions_operator_id"), table_name="sessions")
    op.drop_index(op.f("ix_sessions_device_id"), table_name="sessions")
    op.drop_table("sessions")
    op.drop_index(op.f("ix_jobs_type"), table_name="jobs")
    op.drop_index("ix_jobs_status_created_at", table_name="jobs")
    op.drop_index(op.f("ix_jobs_celery_task_id"), table_name="jobs")
    op.drop_table("jobs")
    op.drop_index(op.f("ix_events_type"), table_name="events")
    op.drop_index("ix_events_entity", table_name="events")
    op.drop_index("ix_events_created_at", table_name="events")
    op.drop_table("events")
    op.drop_table("datasets")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
    op.drop_table("operators")
    op.drop_table("model_versions")
    op.drop_table("devices")
