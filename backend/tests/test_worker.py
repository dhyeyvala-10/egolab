from sqlalchemy import select

from egolabs.models import Event, Job, JobLog, JobStatus
from egolabs.worker import tasks
from egolabs.worker.runtime import job_handler, registered_job_types, run_job


def _job(db, job_type: str, **payload) -> Job:
    job = Job(type=job_type, payload=payload)
    db.add(job)
    db.commit()
    return job


def _logs(db, job: Job) -> list[JobLog]:
    return list(db.scalars(select(JobLog).where(JobLog.job_id == job.id).order_by(JobLog.id)))


def test_healthcheck_job_succeeds_and_writes_structured_logs(db, monkeypatch):
    monkeypatch.setattr(tasks, "check_buckets", lambda: None)
    job = _job(db, "system.healthcheck")

    assert run_job(job.id) == JobStatus.succeeded

    db.refresh(job)
    assert job.status == JobStatus.succeeded
    assert job.attempts == 1
    assert job.started_at is not None and job.finished_at >= job.started_at
    assert job.result == {"database": "ok", "redis": "ok", "ffmpeg": "ok", "storage": "ok"}
    messages = [line.message for line in _logs(db, job)]
    assert messages[0] == "Job started"
    assert messages[-1] == "Job succeeded"
    assert "Database reachable" in messages


def test_healthcheck_reports_storage_failure_without_failing(db, monkeypatch):
    def missing() -> None:
        raise RuntimeError("no bucket")

    monkeypatch.setattr(tasks, "check_buckets", missing)
    job = _job(db, "system.healthcheck")
    assert run_job(job.id) == JobStatus.succeeded
    db.refresh(job)
    assert job.result["storage"].startswith("error")
    assert any(line.level == "warning" for line in _logs(db, job))


def test_failing_handler_marks_job_failed_with_logs_and_event(db):
    @job_handler("test.explode")
    def explode(ctx, payload):
        ctx.info("About to fail", step=1)
        raise ValueError("bad frame index")

    job = _job(db, "test.explode")
    assert run_job(job.id) == JobStatus.failed

    db.refresh(job)
    assert job.status == JobStatus.failed
    assert job.error == "ValueError: bad frame index"
    logs = _logs(db, job)
    assert [line.message for line in logs] == ["Job started", "About to fail", "Job failed"]
    assert logs[1].data == {"step": 1}
    assert "Traceback" in logs[-1].data["traceback"]
    assert db.scalar(select(Event).where(Event.type == "job.failed", Event.entity_id == job.id)) is not None


def test_unknown_job_type_fails_cleanly(db):
    job = _job(db, "does.not.exist")
    assert run_job(job.id) == JobStatus.failed
    db.refresh(job)
    assert "No handler registered" in job.error


def test_finished_jobs_are_not_rerun(db, monkeypatch):
    monkeypatch.setattr(tasks, "check_buckets", lambda: None)
    job = _job(db, "system.healthcheck")
    run_job(job.id)
    before = len(_logs(db, job))
    assert run_job(job.id) == JobStatus.succeeded
    db.refresh(job)
    assert job.attempts == 1
    assert len(_logs(db, job)) == before


def test_registered_job_types():
    assert "system.healthcheck" in registered_job_types()


def test_celery_task_is_registered_under_a_stable_name():
    assert tasks.RUN_JOB_TASK in tasks.celery_app.tasks
