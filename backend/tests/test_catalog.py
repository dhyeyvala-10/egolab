"""Sessions, devices, operators, datasets, and the video library API (spec Phase 1)."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from egolabs.models import CaptureSession, Upload, UploadKind, UploadStatus, Video, VideoStatus
from tests.conftest import auth_header, drain
from tests.media import make_clip, upload_file


@pytest.fixture
def h(admin):
    return auth_header(admin)


def _video(db, name: str, session_id=None, status=VideoStatus.ready, **kw) -> Video:
    video = Video(
        original_filename=name,
        storage_key=f"videos/{uuid.uuid4()}.mp4",
        sha256=uuid.uuid4().hex * 2,
        size_bytes=kw.pop("size_bytes", 1000),
        status=status,
        session_id=session_id,
        **kw,
    )
    db.add(video)
    db.commit()
    return video


# --- sessions --------------------------------------------------------------------------------------


def test_session_names_are_numbered_per_day(client, h):
    day = {"capture_date": "2026-09-23"}
    names = [client.post("/api/v1/sessions", json=day, headers=h).json()["name"] for _ in range(3)]
    assert names == ["SESSION_2026_09_23_001", "SESSION_2026_09_23_002", "SESSION_2026_09_23_003"]
    other = client.post("/api/v1/sessions", json={"capture_date": "2026-09-24"}, headers=h).json()
    assert other["name"] == "SESSION_2026_09_24_001"
    preview = client.get("/api/v1/sessions/next-name", params={"date": "2026-09-23"}, headers=h).json()
    assert preview["name"] == "SESSION_2026_09_23_004"


def test_session_name_defaults_to_the_start_date(client, h):
    body = {"started_at": "2026-08-01T09:00:00Z", "ended_at": "2026-08-01T09:30:00Z"}
    assert client.post("/api/v1/sessions", json=body, headers=h).json()["name"] == "SESSION_2026_08_01_001"
    today = datetime.now(UTC).strftime("%Y_%m_%d")
    assert client.post("/api/v1/sessions", json={}, headers=h).json()["name"] == f"SESSION_{today}_001"


def test_session_validation(client, h, viewer):
    assert client.post("/api/v1/sessions", json={"name": "kitchen"}, headers=h).status_code == 422
    client.post("/api/v1/sessions", json={"name": "SESSION_2026_01_01_007"}, headers=h).raise_for_status()
    assert (
        client.post("/api/v1/sessions", json={"name": "SESSION_2026_01_01_007"}, headers=h).status_code == 409
    )
    backwards = {"started_at": "2026-01-01T10:00:00Z", "ended_at": "2026-01-01T09:00:00Z"}
    assert client.post("/api/v1/sessions", json=backwards, headers=h).status_code == 422
    assert (
        client.post("/api/v1/sessions", json={"device_id": str(uuid.uuid4())}, headers=h).status_code == 422
    )
    assert client.post("/api/v1/sessions", json={}, headers=auth_header(viewer)).status_code == 403


def test_session_metadata_round_trips(client, h):
    device = client.post("/api/v1/devices", json={"name": "Aria-07", "kind": "glasses"}, headers=h).json()
    operator = client.post(
        "/api/v1/operators", json={"name": "R. Patel", "external_id": "OP-12"}, headers=h
    ).json()
    body = {
        "capture_date": "2026-09-23",
        "operator_id": operator["id"],
        "device_id": device["id"],
        "started_at": "2026-09-23T09:00:00Z",
        "ended_at": "2026-09-23T09:42:00Z",
        "environment": "kitchen",
        "task": "make tea",
        "location": "Lab B",
        "capture_conditions": {"lighting": "low", "clutter": "high"},
    }
    created = client.post("/api/v1/sessions", json=body, headers=h).json()
    assert created["operator"] == {"id": operator["id"], "name": "R. Patel"}
    assert created["device"] == {"id": device["id"], "name": "Aria-07"}
    assert created["capture_conditions"] == {"lighting": "low", "clutter": "high"}
    patched = client.patch(
        f"/api/v1/sessions/{created['id']}", json={"task": "make coffee", "device_id": None}, headers=h
    ).json()
    assert (
        patched["task"] == "make coffee" and patched["device"] is None and patched["environment"] == "kitchen"
    )
    assert client.patch(f"/api/v1/sessions/{uuid.uuid4()}", json={}, headers=h).status_code == 404


def test_session_list_filters_sorts_and_counts(client, db, h):
    a = client.post(
        "/api/v1/sessions",
        json={"capture_date": "2026-09-01", "environment": "kitchen", "task": "tea"},
        headers=h,
    ).json()
    b = client.post(
        "/api/v1/sessions",
        json={"capture_date": "2026-09-02", "environment": "workshop", "task": "screws"},
        headers=h,
    ).json()
    _video(db, "a1.mp4", a["id"], duration_s=10, size_bytes=100)
    _video(db, "a2.mp4", a["id"], duration_s=5, size_bytes=50, status=VideoStatus.corrupt)
    _video(db, "b1.mp4", b["id"], duration_s=1, size_bytes=10, status=VideoStatus.processing)

    page = client.get("/api/v1/sessions", params={"sort": "video_count", "order": "desc"}, headers=h).json()
    assert [s["name"] for s in page["items"]] == [a["name"], b["name"]]
    stats = page["items"][0]["stats"]
    assert stats == {"video_count": 2, "ready_count": 1, "processing_count": 0, "corrupt_count": 1,
                     "total_duration_s": 15.0, "total_size_bytes": 150}  # fmt: skip
    assert client.get("/api/v1/sessions", params={"q": "screw"}, headers=h).json()["total"] == 1
    assert (
        client.get("/api/v1/sessions", params={"environment": "kitchen"}, headers=h).json()["items"][0]["id"]
        == a["id"]
    )
    by_name = client.get(
        "/api/v1/sessions", params={"sort": "name", "order": "asc", "limit": 1, "offset": 1}, headers=h
    ).json()
    assert by_name["total"] == 2 and [s["name"] for s in by_name["items"]] == [b["name"]]


def test_session_detail_shows_problems_and_datasets(client, db, h, admin):
    session = client.post("/api/v1/sessions", json={}, headers=h).json()
    _video(db, "bad.mp4", session["id"], status=VideoStatus.corrupt, error="moov atom not found")
    db.add(Upload(filename="lost.zip", size_bytes=1, kind=UploadKind.archive, status=UploadStatus.failed,
                  staging_key="staging/x/lost.zip", part_size=1, session_id=uuid.UUID(session["id"]), error="not a valid ZIP"))  # fmt: skip
    db.add(Upload(filename="busy.mp4", size_bytes=1, kind=UploadKind.video, status=UploadStatus.uploading,
                  staging_key="staging/y/busy.mp4", part_size=1, session_id=uuid.UUID(session["id"])))  # fmt: skip
    db.commit()
    dataset = client.post("/api/v1/datasets", json={"name": "kitchen-v0"}, headers=h).json()
    assert (
        client.post(
            f"/api/v1/datasets/{dataset['id']}/sessions", json={"session_id": session["id"]}, headers=h
        ).status_code
        == 204
    )

    detail = client.get(f"/api/v1/sessions/{session['id']}", headers=h).json()
    assert detail["corrupt_videos"][0]["error"] == "moov atom not found"
    assert [u["filename"] for u in detail["failed_uploads"]] == ["lost.zip"]
    assert detail["active_uploads"] == 1
    assert detail["datasets"] == [{"id": dataset["id"], "name": "kitchen-v0"}]
    assert client.get(f"/api/v1/sessions/{uuid.uuid4()}", headers=h).status_code == 404


# --- devices / operators / datasets ---------------------------------------------------------------


def test_devices(client, db, h, viewer):
    d = client.post(
        "/api/v1/devices", json={"name": "GoPro-3", "kind": "head-mounted", "serial": "C3441"}, headers=h
    ).json()
    assert client.post("/api/v1/devices", json={"name": "GoPro-3"}, headers=h).status_code == 409
    assert client.post("/api/v1/devices", json={"name": "x"}, headers=auth_header(viewer)).status_code == 403
    session = client.post("/api/v1/sessions", json={"device_id": d["id"]}, headers=h).json()
    _video(db, "v.mp4", session["id"])
    listed = client.get("/api/v1/devices", headers=h).json()["items"]
    assert listed[0]["session_count"] == 1 and listed[0]["video_count"] == 1
    patched = client.patch(
        f"/api/v1/devices/{d['id']}", json={"kind": "chest-mounted", "metadata": {"fov": 118}}, headers=h
    ).json()
    assert (
        patched["kind"] == "chest-mounted"
        and patched["metadata"] == {"fov": 118}
        and patched["name"] == "GoPro-3"
    )
    assert client.get("/api/v1/devices", params={"q": "chest"}, headers=h).json()["total"] == 1


def test_operators(client, h):
    client.post("/api/v1/operators", json={"name": "Zed"}, headers=h).raise_for_status()
    client.post("/api/v1/operators", json={"name": "Amy", "external_id": "E1"}, headers=h).raise_for_status()
    assert (
        client.post("/api/v1/operators", json={"name": "Amy 2", "external_id": "E1"}, headers=h).status_code
        == 409
    )
    assert [o["name"] for o in client.get("/api/v1/operators", headers=h).json()["items"]] == ["Amy", "Zed"]


def test_dataset_membership(client, h):
    dataset = client.post("/api/v1/datasets", json={"name": "bench"}, headers=h).json()
    assert client.post("/api/v1/datasets", json={"name": "bench"}, headers=h).status_code == 409
    s1 = client.post("/api/v1/sessions", json={}, headers=h).json()
    url = f"/api/v1/datasets/{dataset['id']}/sessions"
    client.post(url, json={"session_id": s1["id"]}, headers=h)
    client.post(url, json={"session_id": s1["id"]}, headers=h)  # idempotent
    assert client.get("/api/v1/datasets", headers=h).json()["items"][0]["session_count"] == 1
    assert (
        client.get("/api/v1/sessions", params={"dataset_id": dataset["id"]}, headers=h).json()["total"] == 1
    )
    assert client.delete(f"{url}/{s1['id']}", headers=h).status_code == 204
    assert client.get("/api/v1/datasets", headers=h).json()["items"][0]["session_count"] == 0
    assert client.post(url, json={"session_id": str(uuid.uuid4())}, headers=h).status_code == 404


# --- videos ----------------------------------------------------------------------------------------


def test_video_library_filters_sort_and_pagination(client, db, h):
    s = client.post("/api/v1/sessions", json={}, headers=h).json()
    _video(db, "alpha.mp4", s["id"], duration_s=30, codec="h264", width=1920)
    _video(db, "beta.mov", None, duration_s=10, codec="hevc", width=3840)
    _video(db, "gamma.mp4", s["id"], duration_s=None, status=VideoStatus.corrupt)

    def names(**params):
        return [
            v["original_filename"]
            for v in client.get("/api/v1/videos", params=params, headers=h).json()["items"]
        ]

    assert names(sort="duration_s", order="desc") == ["alpha.mp4", "beta.mov", "gamma.mp4"]  # nulls last
    assert names(sort="duration_s", order="asc") == ["beta.mov", "alpha.mp4", "gamma.mp4"]
    assert names(status="corrupt") == ["gamma.mp4"]
    assert names(codec="hevc") == ["beta.mov"]
    assert names(unassigned="true") == ["beta.mov"]
    assert sorted(names(session_id=s["id"])) == ["alpha.mp4", "gamma.mp4"]
    assert names(q="ALPH") == ["alpha.mp4"]
    page = client.get(
        "/api/v1/videos",
        params={"sort": "original_filename", "order": "asc", "limit": 2, "offset": 2},
        headers=h,
    ).json()
    assert page["total"] == 3 and [v["original_filename"] for v in page["items"]] == ["gamma.mp4"]
    first = client.get("/api/v1/videos", params={"q": "alpha"}, headers=h).json()["items"][0]
    assert first["session"] == {"id": s["id"], "name": s["name"]}


def test_video_detail_has_provenance_and_playable_urls(client, db, h, enqueued, tmp_path):
    session = client.post("/api/v1/sessions", json={}, headers=h).json()
    upload = upload_file(client, h, make_clip(tmp_path / "hand.mp4"), session_id=session["id"])
    drain(enqueued)
    video_id = db.get(Upload, uuid.UUID(upload["id"])).video_id
    detail = client.get(f"/api/v1/videos/{video_id}", headers=h).json()
    assert detail["upload_id"] == upload["id"]
    assert (
        detail["lineage"][0]["relation"] == "ingested_as"
        and detail["lineage"][0]["parent_id"] == upload["id"]
    )
    assert detail["probe"]["streams"][0]["codec_name"] == "h264"
    assert detail["proxy_url"].startswith("http") and "Signature" in detail["proxy_url"]
    assert detail["thumbnails_url"]
    listed = client.get("/api/v1/videos", headers=h).json()["items"][0]
    assert listed["thumbnails_url"]
    assert client.get(f"/api/v1/videos/{uuid.uuid4()}", headers=h).status_code == 404


def test_move_video_between_sessions(client, db, h, viewer):
    s1 = client.post("/api/v1/sessions", json={}, headers=h).json()
    video = _video(db, "v.mp4", None)
    moved = client.patch(f"/api/v1/videos/{video.id}", json={"session_id": s1["id"]}, headers=h).json()
    assert moved["session"]["id"] == s1["id"]
    cleared = client.patch(f"/api/v1/videos/{video.id}", json={"session_id": None}, headers=h).json()
    assert cleared["session"] is None
    assert (
        client.patch(
            f"/api/v1/videos/{video.id}", json={"session_id": str(uuid.uuid4())}, headers=h
        ).status_code
        == 422
    )
    assert client.patch(f"/api/v1/videos/{video.id}", json={}, headers=auth_header(viewer)).status_code == 403
    assert db.scalar(select(CaptureSession)) is not None
