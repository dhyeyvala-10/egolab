"""The Annotation Queue: assigning sessions and videos to annotators (spec Phase 2)."""

import uuid

import pytest
from sqlalchemy import select

from egolabs.models import CaptureSession, Event, Video, VideoStatus
from tests.conftest import auth_header, user_with_role


@pytest.fixture
def lead(client, admin):
    return user_with_role(client, admin, "reviewer@example.com", "reviewer", name="Rae Viewer")


@pytest.fixture
def session_with_videos(db):
    s = CaptureSession(name="SESSION_2026_09_23_001")
    db.add(s)
    db.flush()
    videos = [Video(original_filename=f"clip{i}.mp4", storage_key=f"videos/{uuid.uuid4()}.mp4",
                    sha256=uuid.uuid4().hex * 2, size_bytes=1, status=VideoStatus.ready, session_id=s.id,
                    frame_count=300) for i in range(3)]  # fmt: skip
    db.add_all(videos)
    db.commit()
    return s, videos


def _assign(client, headers, **body):
    return client.post("/api/v1/assignments", json=body, headers=headers)


def test_lead_assigns_a_session_and_progress_follows_annotation(
    client, db, lead, annotator, session_with_videos
):
    session, videos = session_with_videos
    res = _assign(client, auth_header(lead), session_id=str(session.id), assignee_id=annotator["user"]["id"],
                  note="Label every reach")  # fmt: skip
    assert res.status_code == 201, res.text
    a = res.json()
    assert a["target_type"] == "session" and a["session"] == {"id": str(session.id), "name": session.name}
    assert a["assignee"]["name"] == "Ann Otator" and a["assigned_by"]["name"] == "Rae Viewer"
    assert (a["status"], a["progress"]) == ("todo", {"videos": 3, "annotated": 0})
    assert db.scalar(select(Event.type).where(Event.entity_id == uuid.UUID(a["id"]))) == "assignment.created"

    h = auth_header(annotator)
    body = {"type": "segment", "label": "reach", "frame_start": 0, "frame_end": 10}
    client.post(f"/api/v1/videos/{videos[0].id}/annotations", json=body, headers=h).raise_for_status()
    mine = client.get("/api/v1/assignments", params={"mine": True}, headers=h).json()
    assert mine["total"] == 1 and mine["items"][0]["progress"] == {"videos": 3, "annotated": 1}

    started = client.patch(f"/api/v1/assignments/{a['id']}", json={"status": "in_progress"}, headers=h).json()
    assert started["status"] == "in_progress" and started["completed_at"] is None
    done = client.patch(f"/api/v1/assignments/{a['id']}", json={"status": "done"}, headers=h).json()
    assert done["status"] == "done" and done["completed_at"] is not None

    # Covering-a-video lookup finds session assignments too (used by the inspector).
    covering = client.get("/api/v1/assignments", params={"video_id": str(videos[1].id)}, headers=h).json()
    assert [x["id"] for x in covering["items"]] == [a["id"]]


def test_single_video_assignment(client, lead, annotator, session_with_videos):
    _, videos = session_with_videos
    res = _assign(client, auth_header(lead), video_id=str(videos[2].id), assignee_id=annotator["user"]["id"])
    assert res.status_code == 201
    a = res.json()
    assert a["target_type"] == "video" and a["video"]["name"] == "clip2.mp4"
    assert a["progress"] == {"videos": 1, "annotated": 0}


def test_who_can_assign(client, admin, lead, annotator, viewer, session_with_videos):
    session, _ = session_with_videos
    body = {"session_id": str(session.id), "assignee_id": annotator["user"]["id"]}
    assert _assign(client, auth_header(annotator), **body).status_code == 403
    assert _assign(client, auth_header(viewer), **body).status_code == 403
    assert _assign(client, auth_header(admin), **body).status_code == 201
    assert _assign(client, auth_header(lead), **body).status_code == 409  # already in their queue
    # Viewers can't receive work; targets must exist; exactly one target.
    assert _assign(client, auth_header(lead), session_id=str(session.id),
                   assignee_id=viewer["user"]["id"]).status_code == 422  # fmt: skip
    assert _assign(client, auth_header(lead), session_id=str(uuid.uuid4()),
                   assignee_id=annotator["user"]["id"]).status_code == 422  # fmt: skip
    assert _assign(client, auth_header(lead), assignee_id=annotator["user"]["id"]).status_code == 422


def test_annotators_update_only_their_own_status(client, admin, lead, annotator, session_with_videos):
    session, _ = session_with_videos
    other = user_with_role(client, admin, "other@example.com", "annotator")
    a = _assign(client, auth_header(lead), session_id=str(session.id), assignee_id=other["user"]["id"]).json()
    url = f"/api/v1/assignments/{a['id']}"
    assert client.patch(url, json={"status": "done"}, headers=auth_header(annotator)).status_code == 403
    assert client.patch(url, json={"note": "mine now"}, headers=auth_header(other)).status_code == 403
    moved = client.patch(url, json={"assignee_id": annotator["user"]["id"]}, headers=auth_header(lead)).json()
    assert moved["assignee"]["id"] == annotator["user"]["id"]
    assert client.delete(url, headers=auth_header(annotator)).status_code == 403
    assert client.delete(url, headers=auth_header(lead)).status_code == 204
    assert client.get("/api/v1/assignments", headers=auth_header(lead)).json()["total"] == 0


def test_list_filters_and_assignable_users(client, admin, lead, annotator, viewer, session_with_videos):
    session, videos = session_with_videos
    h = auth_header(lead)
    _assign(client, h, session_id=str(session.id), assignee_id=annotator["user"]["id"])
    done = _assign(client, h, video_id=str(videos[0].id), assignee_id=lead["user"]["id"]).json()
    client.patch(f"/api/v1/assignments/{done['id']}", json={"status": "done"}, headers=h)

    everything = client.get("/api/v1/assignments", headers=h).json()["items"]
    assert [x["status"] for x in everything] == ["todo", "done"]  # open work first
    todo = client.get("/api/v1/assignments", params={"status": ["todo", "in_progress"]}, headers=h).json()
    assert todo["total"] == 1
    by_person = client.get(
        "/api/v1/assignments", params={"assignee_id": lead["user"]["id"]}, headers=h
    ).json()
    assert by_person["total"] == 1

    people = client.get("/api/v1/users/assignable", headers=auth_header(annotator)).json()
    assert {p["email"] for p in people} == {
        "admin@example.com",
        "reviewer@example.com",
        "annotator@example.com",
    }
