"""uploads and ingest provenance

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-23 12:23:59.300123
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "uploads",
        sa.Column("filename", sa.String(length=1024), nullable=False),
        sa.Column("content_type", sa.String(length=200), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "video",
                "archive",
                "sidecar",
                name="upload_kind",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "uploading",
                "processing",
                "processed",
                "duplicate",
                "failed",
                "aborted",
                name="upload_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("staging_key", sa.String(length=1024), nullable=False),
        sa.Column("s3_upload_id", sa.String(length=1024), nullable=True),
        sa.Column("part_size", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=True),
        sa.Column("sequence_fps", sa.Float(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("video_id", sa.UUID(), nullable=True),
        sa.Column("job_id", sa.UUID(), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "sequence_fps IS NULL OR sequence_fps > 0", name=op.f("ck_uploads_sequence_fps_positive")
        ),
        sa.CheckConstraint("size_bytes >= 0", name=op.f("ck_uploads_size_non_negative")),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_uploads_created_by_users"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name=op.f("fk_uploads_job_id_jobs"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sessions.id"], name=op.f("fk_uploads_session_id_sessions"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["video_id"], ["videos.id"], name=op.f("fk_uploads_video_id_videos"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_uploads")),
        sa.UniqueConstraint("staging_key", name=op.f("uq_uploads_staging_key")),
    )
    op.create_index(op.f("ix_uploads_session_id"), "uploads", ["session_id"], unique=False)
    op.create_index(op.f("ix_uploads_status"), "uploads", ["status"], unique=False)
    op.create_table(
        "metadata_files",
        sa.Column("upload_id", sa.UUID(), nullable=True),
        sa.Column("session_id", sa.UUID(), nullable=True),
        sa.Column("video_id", sa.UUID(), nullable=True),
        sa.Column("filename", sa.String(length=1024), nullable=False),
        sa.Column("format", sa.String(length=8), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("parsed", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name=op.f("fk_metadata_files_session_id_sessions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["upload_id"],
            ["uploads.id"],
            name=op.f("fk_metadata_files_upload_id_uploads"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["video_id"], ["videos.id"], name=op.f("fk_metadata_files_video_id_videos"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_metadata_files")),
    )
    op.create_index(op.f("ix_metadata_files_session_id"), "metadata_files", ["session_id"], unique=False)
    op.create_index(op.f("ix_metadata_files_video_id"), "metadata_files", ["video_id"], unique=False)
    op.add_column(
        "videos",
        sa.Column(
            "source_kind",
            sa.Enum(
                "file",
                "archive_member",
                "image_sequence",
                name="video_source",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="file",
            nullable=False,
        ),
    )
    op.add_column("videos", sa.Column("upload_id", sa.UUID(), nullable=True))
    op.add_column("videos", sa.Column("source_path", sa.String(length=1024), nullable=True))
    op.add_column("videos", sa.Column("bit_rate", sa.BigInteger(), nullable=True))
    op.add_column("videos", sa.Column("has_audio", sa.Boolean(), nullable=True))
    op.add_column(
        "videos",
        sa.Column(
            "derivatives", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
    )
    op.create_index(op.f("ix_videos_upload_id"), "videos", ["upload_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_videos_upload_id_uploads"),
        "videos",
        "uploads",
        ["upload_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_videos_upload_id_uploads"), "videos", type_="foreignkey")
    op.drop_index(op.f("ix_videos_upload_id"), table_name="videos")
    op.drop_column("videos", "derivatives")
    op.drop_column("videos", "has_audio")
    op.drop_column("videos", "bit_rate")
    op.drop_column("videos", "source_path")
    op.drop_column("videos", "upload_id")
    op.drop_column("videos", "source_kind")
    op.drop_index(op.f("ix_metadata_files_video_id"), table_name="metadata_files")
    op.drop_index(op.f("ix_metadata_files_session_id"), table_name="metadata_files")
    op.drop_table("metadata_files")
    op.drop_index(op.f("ix_uploads_status"), table_name="uploads")
    op.drop_index(op.f("ix_uploads_session_id"), table_name="uploads")
    op.drop_table("uploads")
