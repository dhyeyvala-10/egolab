from egolabs.events import record_event
from egolabs.models import CaptureSession, Dataset, Job, JobStatus, Video
from tests.conftest import auth_header


def test_overview_requires_auth(client):
    assert client.get("/api/v1/overview").status_code == 401


def test_overview_on_an_empty_database(client, admin):
    body = client.get("/api/v1/overview", headers=auth_header(admin)).json()
    assert body["counts"] == {"datasets": 0, "sessions": 0, "videos": 0, "jobs_active": 0}
    assert body["recent_jobs"] == []
    # registering the admin is the only activity so far
    assert [e["type"] for e in body["recent_events"]] == ["user.registered"]


def test_overview_counts_come_from_the_database(client, db, admin):
    db.add(Dataset(name="bench-v1"))
    session = CaptureSession(name="SESSION_2026_09_23_001")
    db.add(session)
    db.flush()
    db.add_all(
        [
            Video(
                session_id=session.id,
                original_filename=f"clip{i}.mp4",
                storage_key=f"raw/{i}",
                sha256=f"{i:064x}",
                size_bytes=1000 + i,
            )
            for i in range(3)
        ]
    )
    db.add_all([Job(type="ingest.probe", status=s) for s in JobStatus])
    record_event(db, "session.uploaded", "Session uploaded: SESSION_2026_09_23_001")
    db.commit()

    body = client.get("/api/v1/overview", headers=auth_header(admin)).json()
    assert body["counts"] == {
        "datasets": 1,
        "sessions": 1,
        "videos": 3,
        "jobs_active": 3,
    }  # queued, running, retrying
    assert len(body["recent_jobs"]) == len(JobStatus)
    assert body["recent_events"][0]["type"] == "session.uploaded"  # newest first
