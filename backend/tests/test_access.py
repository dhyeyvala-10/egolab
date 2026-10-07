"""The owner's control: nobody else is admin, newcomers wait for access, limits send big uploads and long videos
to the owner first, only the owner starts processing unless they allow editors, and people don't see each
other's uploads or activity."""

import uuid

import httpx
import pytest
from sqlalchemy import select, text

from egolabs.config import get_settings
from egolabs.db import get_engine
from egolabs.models import ProcessingHold, Upload, User, Video
from tests.conftest import auth_header, drain, register, user_with_role
from tests.media import make_clip, put_parts, upload_file
from tests.test_pipelines import CHECKS, P, create


def _limits(client, admin, **values) -> dict:
    res = client.patch("/api/v1/settings/limits", json=values, headers=auth_header(admin))
    assert res.status_code == 200, res.text
    return res.json()


@pytest.fixture
def editor(client, admin):
    return user_with_role(client, admin, "ed@example.com", "annotator", name="Ed Itor")


def test_owner_email_decides_who_is_admin(client, db, monkeypatch):
    monkeypatch.setattr(get_settings(), "owner_email", "Boss@Example.com")
    first = register(client, "early@example.com")
    assert (first["user"]["role"], first["user"]["is_owner"]) == ("pending", False)
    boss = register(client, "boss@example.com")
    assert (boss["user"]["role"], boss["user"]["is_owner"]) == ("admin", True)

    # Someone made admin behind the app's back loses it on their next request.
    db.execute(text("UPDATE users SET role = 'admin' WHERE email = 'early@example.com'"))
    db.commit()
    assert client.get("/api/v1/auth/me", headers=auth_header(first)).json()["role"] == "pending"

    # A new OWNER_EMAIL takes over: the previous owner keeps nothing.
    monkeypatch.setattr(get_settings(), "owner_email", "early@example.com")
    me = client.get("/api/v1/auth/me", headers=auth_header(first)).json()
    assert (me["role"], me["is_owner"]) == ("admin", True)
    db.expire_all()
    old = db.scalar(select(User).where(User.email == "boss@example.com"))
    assert (old.role.value, old.is_owner) == ("pending", False)


def test_owner_email_can_name_several_admins(client, db, monkeypatch):
    monkeypatch.setattr(get_settings(), "owner_email", " one@example.com, Two@Example.com ")
    one, two = register(client, "one@example.com"), register(client, "two@example.com")
    other = register(client, "other@example.com")
    assert [(u["user"]["role"], u["user"]["is_owner"]) for u in (one, two, other)] == [
        ("admin", True), ("admin", True), ("pending", False),
    ]  # fmt: skip
    # Both are full admins, and neither can change the other from the app.
    for me, them in ((one, two), (two, one)):
        assert client.get("/api/v1/users", headers=auth_header(me)).status_code == 200
        res = client.patch(
            f"/api/v1/users/{them['user']['id']}", json={"role": "viewer"}, headers=auth_header(me)
        )
        assert res.status_code == 409
    # Taken out of OWNER_EMAIL: no longer admin on the next request.
    monkeypatch.setattr(get_settings(), "owner_email", "one@example.com")
    me = client.get("/api/v1/auth/me", headers=auth_header(two)).json()
    assert (me["role"], me["is_owner"]) == ("pending", False)


def test_a_newcomer_sees_nothing_until_given_access(client, admin):
    newcomer = register(client, "new@example.com")
    h = auth_header(newcomer)
    assert client.get("/api/v1/auth/me", headers=h).json()["role"] == "pending"
    for path in ("/api/v1/overview", "/api/v1/videos", "/api/v1/uploads", "/api/v1/sessions"):
        res = client.get(path, headers=h)
        assert res.status_code == 403 and "waiting for the admin" in res.json()["detail"], path
    res = client.post("/api/v1/uploads", json={"filename": "a.mp4", "size_bytes": 10}, headers=h)
    assert res.status_code == 403


def test_an_upload_over_the_size_limit_waits_for_the_owner(client, db, admin, editor, enqueued, tmp_path):
    assert _limits(client, admin, upload_max_bytes=1000)["upload_max_bytes"] == 1000
    clip = make_clip(tmp_path / "big.mp4", seconds=1)
    data = clip.read_bytes()
    assert len(data) > 1000
    h = auth_header(editor)
    up = client.post(
        "/api/v1/uploads", json={"filename": "big.mp4", "size_bytes": len(data)}, headers=h
    ).json()
    assert up["status"] == "awaiting_approval" and up["approval_reason"].endswith(
        "over the 1.0 KB upload limit"
    )
    # Nothing can be sent yet.
    res = client.post(f"/api/v1/uploads/{up['id']}/parts", json={"part_numbers": [1]}, headers=h)
    assert res.status_code == 409

    requests = client.get("/api/v1/requests", headers=auth_header(admin)).json()
    assert [(u["filename"], u["uploaded_by_email"]) for u in requests["uploads"]] == [
        ("big.mp4", "ed@example.com")
    ]
    assert client.get("/api/v1/requests", headers=h).status_code == 403
    assert client.post(f"/api/v1/uploads/{up['id']}/approve", headers=h).status_code == 403

    allowed = client.post(f"/api/v1/uploads/{up['id']}/approve", headers=auth_header(admin)).json()
    assert allowed["status"] == "uploading"
    parts = put_parts(client, h, up, data, range(1, up["part_count"] + 1))
    done = client.post(f"/api/v1/uploads/{up['id']}/complete", json={"parts": parts}, headers=h)
    assert done.status_code == 202
    drain(enqueued)
    assert client.get(f"/api/v1/uploads/{up['id']}", headers=h).json()["status"] == "processed"

    # A second one is rejected; the uploader sees why. The owner's own uploads never wait.
    other = client.post("/api/v1/uploads", json={"filename": "b.mp4", "size_bytes": 5000}, headers=h).json()
    client.post(f"/api/v1/uploads/{other['id']}/reject", json={"reason": "Too big for now"},
                headers=auth_header(admin)).raise_for_status()  # fmt: skip
    seen = client.get(f"/api/v1/uploads/{other['id']}", headers=h).json()
    assert (seen["status"], seen["error"]) == ("rejected", "Too big for now")
    mine = client.post(
        "/api/v1/uploads", json={"filename": "c.mp4", "size_bytes": 5000}, headers=auth_header(admin)
    )
    assert mine.json()["status"] == "uploading"


def test_the_uploader_can_cancel_a_request_and_the_admin_can_cancel_any_upload(client, db, admin, editor):
    _limits(client, admin, upload_max_bytes=1000)
    h = auth_header(editor)
    waiting = client.post("/api/v1/uploads", json={"filename": "w.mp4", "size_bytes": 5000}, headers=h).json()
    assert client.delete(f"/api/v1/uploads/{waiting['id']}", headers=h).status_code == 204
    assert client.get(f"/api/v1/uploads/{waiting['id']}", headers=h).json()["status"] == "aborted"

    going = client.post("/api/v1/uploads", json={"filename": "g.mp4", "size_bytes": 500}, headers=h).json()
    assert client.delete(f"/api/v1/uploads/{going['id']}", headers=auth_header(admin)).status_code == 204
    assert client.get(f"/api/v1/uploads/{going['id']}", headers=h).json()["status"] == "aborted"
    activity = client.get("/api/v1/users/activity", headers=auth_header(admin)).json()["items"]
    assert activity[0]["message"] == "Upload cancelled by the admin: g.mp4"


def test_uploads_show_who_sent_them_and_how_far_they_got(client, admin, editor, tmp_path):
    h = auth_header(editor)
    data = b"x" * (5 * 1024 * 1024 + 10)
    up = client.post("/api/v1/uploads", json={"filename": "p.mp4", "size_bytes": len(data)}, headers=h).json()
    assert up["part_count"] == 1
    listed = client.get("/api/v1/uploads", headers=auth_header(admin)).json()["items"][0]
    assert (listed["uploaded_by_email"], listed["uploaded_by_name"]) == ("ed@example.com", "Ed Itor")
    assert (listed["received_bytes"], listed["last_data_at"]) == (0, None)

    urls = client.post(f"/api/v1/uploads/{up['id']}/parts", json={"part_numbers": [1]}, headers=h).json()[
        "urls"
    ]
    httpx.put(urls[0]["url"], content=data).raise_for_status()
    listed = client.get("/api/v1/uploads", headers=auth_header(admin)).json()["items"][0]
    assert listed["received_bytes"] == len(data) and listed["last_data_at"] is not None


def test_people_see_only_their_own_uploads_and_activity(client, db, admin, editor, enqueued, tmp_path):
    other = user_with_role(client, admin, "other@example.com", "annotator")
    upload_file(client, auth_header(editor), make_clip(tmp_path / "eds.mp4", seconds=1))
    drain(enqueued)
    theirs = client.get("/api/v1/uploads", headers=auth_header(other)).json()
    assert theirs["total"] == 0
    eds = client.get("/api/v1/uploads", headers=auth_header(editor)).json()["items"]
    assert [u["filename"] for u in eds] == ["eds.mp4"]
    assert client.get(f"/api/v1/uploads/{eds[0]['id']}", headers=auth_header(other)).status_code == 404
    assert client.get("/api/v1/uploads", headers=auth_header(admin)).json()["total"] == 1

    def messages(who) -> list[str]:
        return [
            e["message"]
            for e in client.get("/api/v1/overview", headers=auth_header(who)).json()["recent_events"]
        ]

    assert not any("eds.mp4" in m for m in messages(other))
    assert any("eds.mp4" in m for m in messages(editor))
    assert any("eds.mp4" in m for m in messages(admin))
    # Others' jobs aren't shown either.
    assert client.get("/api/v1/overview", headers=auth_header(other)).json()["recent_jobs"] == []


def test_a_video_over_the_length_limit_is_held_until_the_owner_allows_it(
    client, db, admin, editor, enqueued, tmp_path
):
    _limits(client, admin, video_max_seconds=0.5, processing_by="editors")
    auto = create(client, auth_header(admin), CHECKS, name="On upload")
    client.put(
        f"{P}/{auto['id']}", json={"run_on_upload": True}, headers=auth_header(admin)
    ).raise_for_status()

    up = upload_file(client, auth_header(editor), make_clip(tmp_path / "long.mp4", seconds=1))
    drain(enqueued)
    db.expire_all()
    video = db.get(Video, db.get(Upload, uuid.UUID(up["id"])).video_id)
    assert video.processing_hold == ProcessingHold.held and video.hold_reason.endswith("length limit")
    runs = client.get(f"{P}/runs", params={"pipeline_id": auto["id"]}, headers=auth_header(admin)).json()
    assert runs["total"] == 0

    # Nothing can process it by hand either.
    res = client.post(
        f"{P}/{auto['id']}/runs", json={"inputs": {"video_ids": [str(video.id)]}}, headers=auth_header(editor)
    )
    assert res.status_code == 422
    res = client.post("/api/v1/cv/runs", json={"video_ids": [str(video.id)]}, headers=auth_header(editor))
    assert res.status_code == 409 and "Waiting for the admin" in res.json()["detail"]

    held = client.get("/api/v1/requests", headers=auth_header(admin)).json()["videos"]
    assert [(v["filename"], v["uploaded_by_email"]) for v in held] == [("long.mp4", "ed@example.com")]
    client.post(f"/api/v1/requests/videos/{video.id}/allow", headers=auth_header(admin)).raise_for_status()
    drain(enqueued)
    runs = client.get(f"{P}/runs", params={"pipeline_id": auto["id"]}, headers=auth_header(admin)).json()
    assert runs["total"] == 1 and runs["items"][0]["status"] == "succeeded"
    assert client.get("/api/v1/requests", headers=auth_header(admin)).json()["videos"] == []


def test_the_owners_own_long_videos_are_not_held(client, db, admin, enqueued, tmp_path):
    _limits(client, admin, video_max_seconds=0.5)
    up = upload_file(client, auth_header(admin), make_clip(tmp_path / "mine.mp4", seconds=1))
    drain(enqueued)
    db.expire_all()
    assert db.get(Video, db.get(Upload, uuid.UUID(up["id"])).video_id).processing_hold is None


def test_only_the_owner_starts_processing_unless_they_allow_editors(client, admin, editor):
    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM app_settings WHERE key = 'processing_by'"))
    assert client.get("/api/v1/settings/limits", headers=auth_header(editor)).json() == {
        "upload_max_bytes": 1_000_000_000, "video_max_seconds": None, "processing_by": "owner",
    }  # fmt: skip
    res = client.post(P, json={"name": "Mine", "graph": CHECKS}, headers=auth_header(editor))
    assert res.status_code == 403 and res.json()["detail"] == "Only the admin can start processing"
    res = client.post("/api/v1/cv/runs", json={"video_ids": [str(uuid.uuid4())]}, headers=auth_header(editor))
    assert res.status_code == 403
    assert (
        client.post(P, json={"name": "Owner's", "graph": CHECKS}, headers=auth_header(admin)).status_code
        == 201
    )

    _limits(client, admin, processing_by="editors")
    assert (
        client.post(P, json={"name": "Mine", "graph": CHECKS}, headers=auth_header(editor)).status_code == 201
    )
    assert client.patch("/api/v1/settings/limits", json={"processing_by": "owner"},
                        headers=auth_header(editor)).status_code == 403  # fmt: skip
