"""Cron schedules: each fires its pipeline's latest version on the videos its selector picks."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from egolabs.models import Pipeline, PipelineSchedule, PipelineVersion, RunTrigger
from egolabs.pipelines import cron, inputs


def latest_version(db: Session, pipeline_id: uuid.UUID) -> PipelineVersion | None:
    return db.scalar(
        select(PipelineVersion)
        .where(PipelineVersion.pipeline_id == pipeline_id)
        .order_by(PipelineVersion.number.desc())
        .limit(1)
    )


def next_run(schedule: PipelineSchedule, after: datetime) -> datetime:
    return cron.next_after(cron.parse(schedule.cron), after, schedule.timezone)


def fire(db: Session, schedule: PipelineSchedule, now: datetime, *, user_id: uuid.UUID | None = None,
         manual: bool = False) -> tuple[str, list[uuid.UUID], uuid.UUID | None]:  # fmt: skip
    """Start a run for `schedule` (caller commits, then sends). Returns (outcome, jobs to send, run id)."""
    from egolabs.pipelines import engine

    pipeline = db.get(Pipeline, schedule.pipeline_id)
    version = latest_version(db, schedule.pipeline_id)
    run_id = None
    to_send: list[uuid.UUID] = []
    if pipeline is None or version is None or pipeline.archived_at is not None:
        outcome = "Skipped: the pipeline is archived or has no version"
    else:
        try:
            sel = inputs.RunInputs.model_validate(schedule.inputs or {})
            videos = inputs.resolve(db, sel, only_new_for=pipeline.id if schedule.only_new else None)
        except (inputs.InputError, ValueError) as exc:
            videos, outcome = [], f"Skipped: {exc}"
        else:
            if not videos:
                outcome = "No new videos to process" if schedule.only_new else "No videos matched"
            else:
                run, to_send = engine.start_run(db, version, videos, schedule.inputs or {}, trigger=RunTrigger.schedule,
                                                user_id=user_id or schedule.created_by, schedule_id=schedule.id)  # fmt: skip
                run_id = run.id
                outcome = f"Started run #{run.number} on {len(videos)} video{'s' if len(videos) != 1 else ''}"
    schedule.last_run_at, schedule.last_outcome = now, outcome + (" (run now)" if manual else "")
    return outcome, to_send, run_id


def fire_due(db: Session, now: datetime | None = None) -> int:
    """Fire every enabled schedule whose time has come, and move each to its next time."""
    from egolabs.pipelines import engine

    now = now or datetime.now(UTC)
    due = db.scalars(
        select(PipelineSchedule)
        .where(PipelineSchedule.enabled, PipelineSchedule.next_run_at <= now)
        .with_for_update(skip_locked=True)
        .limit(100)
    ).all()
    fired = 0
    for schedule in due:
        _, to_send, _ = fire(db, schedule, now)
        try:
            schedule.next_run_at = next_run(schedule, now)
        except cron.CronError as exc:
            schedule.enabled, schedule.next_run_at = False, None
            schedule.last_outcome = f"Disabled: {exc}"
        db.commit()
        engine.send(db, to_send)
        fired += 1
    return fired
