"""pipelines that run on new uploads

A pipeline can run by itself on every newly uploaded video once it's ready (`run_on_upload`); such runs have
the trigger `upload`.

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-25 06:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pipelines", sa.Column("run_on_upload", sa.Boolean(), server_default="false", nullable=False)
    )
    # New run trigger (enums are VARCHAR + CHECK, see models.base.str_enum).
    op.drop_constraint(op.f("ck_pipeline_runs_pipeline_run_trigger"), "pipeline_runs", type_="check")
    op.create_check_constraint(
        "pipeline_run_trigger", "pipeline_runs", "trigger IN ('manual', 'schedule', 'upload')"
    )


def downgrade() -> None:
    op.execute("UPDATE pipeline_runs SET trigger = 'manual' WHERE trigger = 'upload'")
    op.drop_constraint(op.f("ck_pipeline_runs_pipeline_run_trigger"), "pipeline_runs", type_="check")
    op.create_check_constraint("pipeline_run_trigger", "pipeline_runs", "trigger IN ('manual', 'schedule')")
    op.drop_column("pipelines", "run_on_upload")
