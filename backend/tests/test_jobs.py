import uuid

from egolabs.models import Job, JobLog, LogLevel
from tests.conftest import auth_header


def test_enqueue_healthcheck_is_admin_only(client, admin, viewer, enqueued):
    assert client.post("/api/v1/jobs/healthcheck", headers=auth_header(viewer)).status_code == 403
    res = client.post("/api/v1/jobs/healthcheck", headers=auth_header(admin))
    assert res.status_code == 202
    job = res.json()
    assert job["type"] == "system.healthcheck"
    assert job["status"] == "queued"
    assert enqueued == [job["id"]]


def test_enqueue_stores_the_celery_task_id(client, db, admin, enqueued):
    job_id = client.post("/api/v1/jobs/healthcheck", headers=auth_header(admin)).json()["id"]
    job = db.get(Job, uuid.UUID(job_id))
    assert job.celery_task_id == "celery-1"
    assert str(job.created_by) == admin["user"]["id"]


def test_get_job_and_404(client, db, viewer):
    job = Job(type="ingest.probe", payload={"video_id": "abc"})
    db.add(job)
    db.commit()
    res = client.get(f"/api/v1/jobs/{job.id}", headers=auth_header(viewer))
    assert res.status_code == 200
    assert res.json()["payload"] == {"video_id": "abc"}
    missing = client.get(f"/api/v1/jobs/{uuid.uuid4()}", headers=auth_header(viewer))
    assert missing.status_code == 404
    assert client.get(f"/api/v1/jobs/{job.id}").status_code == 401


def test_job_logs_are_cursor_paginated(client, db, viewer):
    job = Job(type="ingest.probe")
    db.add(job)
    db.flush()
    db.add_all(
        [JobLog(job_id=job.id, level=LogLevel.info, message=f"step {i}", data={"i": i}) for i in range(5)]
    )
    db.commit()

    headers = auth_header(viewer)
    first = client.get(f"/api/v1/jobs/{job.id}/logs", params={"limit": 3}, headers=headers).json()
    assert [line["message"] for line in first["items"]] == ["step 0", "step 1", "step 2"]
    assert first["next_after_id"] is not None
    rest = client.get(
        f"/api/v1/jobs/{job.id}/logs",
        params={"limit": 3, "after_id": first["next_after_id"]},
        headers=headers,
    ).json()
    assert [line["data"]["i"] for line in rest["items"]] == [3, 4]
    assert rest["next_after_id"] is None
    assert client.get(f"/api/v1/jobs/{uuid.uuid4()}/logs", headers=headers).status_code == 404
