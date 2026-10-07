"""Celery tasks and job handlers."""

from typing import Any

from redis import Redis
from sqlalchemy import text

from egolabs import render as _render  # noqa: F401  (registers video.render_annotated)
from egolabs.config import get_settings
from egolabs.cv import objects as _object_handlers  # noqa: F401  (registers cv.object_detection)
from egolabs.cv import pipeline as _cv_handlers  # noqa: F401  (registers cv.hand_tracking)
from egolabs.cv.movement import job as _movement_handlers  # noqa: F401  (registers cv.movement)
from egolabs.datasets import (
    build as _dataset_build,  # noqa: F401  (registers datasets.build_version, verify_version)
)
from egolabs.datasets import export as _dataset_export  # noqa: F401  (registers datasets.export)
from egolabs.ingest import pipeline as _ingest_handlers  # noqa: F401  (registers ingest.* job handlers)
from egolabs.ingest.probe import ProbeError, tool_versions
from egolabs.pipelines import engine as _pipeline_steps  # noqa: F401  (registers pipeline.* step jobs)
from egolabs.storage import check_buckets
from egolabs.worker.celery_app import celery_app
from egolabs.worker.runtime import JobContext, job_handler, run_job

RUN_JOB_TASK = "egolabs.run_job"
TICK_TASK = "egolabs.pipelines.tick"


@celery_app.task(name=RUN_JOB_TASK)
def run_job_task(job_id: str) -> str:
    return run_job(job_id).value


@celery_app.task(name=TICK_TASK)
def pipelines_tick() -> dict[str, int]:
    """Once a minute (the scheduler service): fire due schedules, retry due steps, recover orphaned jobs."""
    from egolabs.db import get_sessionmaker

    with get_sessionmaker()() as db:
        return _pipeline_steps.tick(db)


@job_handler("system.healthcheck")
def healthcheck(ctx: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
    """Check that the worker can reach the database, Redis, and object storage."""
    results: dict[str, str] = {}

    with ctx.session() as db:
        db.execute(text("SELECT 1"))
    results["database"] = "ok"
    ctx.info("Database reachable")

    Redis.from_url(get_settings().redis_url, socket_timeout=2).ping()
    results["redis"] = "ok"
    ctx.info("Redis reachable")

    try:
        versions = tool_versions()
        results["ffmpeg"] = "ok"
        ctx.info("ffmpeg available", **versions)
    except ProbeError as exc:  # reported, not fatal: only ingestion needs it
        results["ffmpeg"] = f"error: {exc}"
        ctx.warning("ffmpeg not available", error=str(exc))

    try:
        check_buckets()
        results["storage"] = "ok"
        ctx.info("Object storage buckets present")
    except Exception as exc:  # storage is reported, not fatal, so the check still completes
        results["storage"] = f"error: {type(exc).__name__}: {exc}"[:300]
        ctx.warning("Object storage check failed", error=str(exc))

    return results
