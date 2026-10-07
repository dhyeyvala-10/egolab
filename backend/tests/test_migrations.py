from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect

from egolabs.db import get_engine
from egolabs.models import Base
from tests.conftest import alembic_config

CORE_TABLES = {
    "users",
    "datasets",
    "dataset_sessions",
    "sessions",
    "videos",
    "frames",
    "devices",
    "operators",
    "jobs",
    "job_logs",
    "model_versions",
    "annotations",
    "events",
    "lineage_edges",
}


def test_migrations_create_every_core_table():
    assert set(inspect(get_engine()).get_table_names()) >= CORE_TABLES


def test_models_match_migrations():
    with get_engine().connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
    assert diff == []


def test_downgrade_to_empty_and_upgrade_again():
    cfg = alembic_config()
    get_engine().dispose()
    command.downgrade(cfg, "base")
    assert set(inspect(get_engine()).get_table_names()) == {"alembic_version"}
    command.upgrade(cfg, "head")
    assert set(inspect(get_engine()).get_table_names()) >= CORE_TABLES
