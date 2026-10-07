"""Manual annotation, edit history, AI corrections, and the timeline (spec Phase 2)."""

import uuid

import pytest
from sqlalchemy import insert, select

from egolabs.models import Annotation, AnnotationRevision, ModelVersion, Video, VideoStatus
from tests.conftest import auth_header


@pytest.fixture
def h(annotator):
    return auth_header(annotator)


@pytest.fixture
def video(db) -> Video:
    v = Video(original_filename="kitchen.mp4", storage_key=f"videos/{uuid.uuid4()}.mp4", sha256=uuid.uuid4().hex * 2,
              size_bytes=1, status=VideoStatus.ready, frame_count=54_000, fps=30.0)  # fmt: skip
    db.add(v)
    db.commit()
    return v


def _url(video: Video, path: str = "") -> str:
    return f"/api/v1/videos/{video.id}/annotations{path}"


def _create(client, h, video, **body) -> dict:
    body = {"type": "segment", "label": "reach", "frame_start": 10, "frame_end": 20, **body}
    res = client.post(_url(video), json=body, headers=h)
    assert res.status_code == 201, res.text
    return res.json()


def _auto(db, video, **kw) -> Annotation:
    model = db.scalar(select(ModelVersion)) or ModelVersion(name="hands", version="1", kind="hand_tracking",
                                                            adapter="egolabs.cv.Fake")  # fmt: skip
    db.add(model)
    db.flush()
    a = Annotation(video_id=video.id, type=kw.pop("type", "bbox"), label=kw.pop("label", "hand"),
                   frame_start=kw.pop("frame_start", 100), frame_end=kw.pop("frame_end", 100),
                   data=kw.pop("data", {"box": [0.1, 0.1, 0.2, 0.2]}), source="auto", confidence=0.83,
                   model_version_id=model.id, **kw)  # fmt: skip
    db.add(a)
    db.commit()
    return a


def _history(client, h, annotation_id) -> dict:
    res = client.get(f"/api/v1/annotations/{annotation_id}/history", headers=h)
    assert res.status_code == 200, res.text
    return res.json()


# --- create -----------------------------------------------------------------------------------------


def test_create_each_annotation_type(client, h, video, annotator):
    seg = _create(client, h, video)
    assert (seg["source"], seg["revision"], seg["needs_review"], seg["category"]) == (
        "human",
        1,
        False,
        "general",
    )
    assert seg["author"] == {"id": annotator["user"]["id"], "name": "Ann Otator"}

    box = _create(client, h, video, type="bbox", label="mug", category="object", frame_start=5, frame_end=5,
                  data={"box": [0.25, 0.5, 0.5, 0.25]})  # fmt: skip
    assert box["data"] == {"box": [0.25, 0.5, 0.5, 0.25]}

    kp = _create(client, h, video, type="keypoint", label="right hand", category="hand", frame_start=7,
                 frame_end=7, data={"points": [{"name": "wrist", "x": 0.4, "y": 0.6},
                                               {"name": "index_tip", "x": 0.5, "y": 0.4, "visible": False}]})  # fmt: skip
    assert kp["data"]["points"][0] == {"name": "wrist", "x": 0.4, "y": 0.6, "visible": True}

    page = client.get(_url(video), headers=h).json()
    assert [a["id"] for a in page["items"]] == [box["id"], kp["id"], seg["id"]]  # by start frame
    assert page["total"] == 3


@pytest.mark.parametrize(
    "body",
    [
        {"type": "bbox", "data": {"box": [0.8, 0.1, 0.5, 0.1]}},  # off the right edge
        {"type": "bbox", "data": {"box": [0.1, 0.1, 0, 0.1]}},  # zero width
        {"type": "bbox", "data": {}},
        {"type": "segment", "data": {"box": [0, 0, 1, 1]}},  # segments carry no geometry
        {"type": "keypoint", "data": {"points": []}},
        {
            "type": "keypoint",
            "data": {"points": [{"name": "a", "x": 0, "y": 0}, {"name": "a", "x": 1, "y": 1}]},
        },
        {"frame_start": 20, "frame_end": 10},
        {"frame_start": 0, "frame_end": 54_000},  # past the last frame (0–53,999)
        {"label": "   "},
    ],
)
def test_create_rejects_invalid_annotations(client, h, video, body):
    body = {"type": "segment", "label": "x", "frame_start": 0, "frame_end": 1, "data": {}, **body}
    assert client.post(_url(video), json=body, headers=h).status_code == 422


def test_viewers_cannot_annotate(client, video, viewer):
    body = {"type": "segment", "label": "x", "frame_start": 0, "frame_end": 1}
    assert client.post(_url(video), json=body, headers=auth_header(viewer)).status_code == 403
    assert client.get(_url(video), headers=auth_header(viewer)).status_code == 200


# --- edit history -----------------------------------------------------------------------------------


def test_every_edit_is_kept_in_history(client, h, video, admin):
    a = _create(client, h, video)
    res = client.patch(f"/api/v1/annotations/{a['id']}", json={"label": "grasp", "frame_end": 25, "revision": 1},
                       headers=h)  # fmt: skip
    assert res.status_code == 200, res.text
    edited = res.json()
    assert (edited["id"], edited["label"], edited["frame_end"], edited["revision"]) == (
        a["id"],
        "grasp",
        25,
        2,
    )

    # A second person edits; a stale revision is refused rather than silently overwritten.
    client.patch(f"/api/v1/annotations/{a['id']}", json={"label": "pinch"}, headers=auth_header(admin))
    stale = client.patch(f"/api/v1/annotations/{a['id']}", json={"label": "tap", "revision": 2}, headers=h)
    assert stale.status_code == 409

    history = _history(client, h, a["id"])
    revs = history["revisions"]
    assert [(r["revision"], r["action"]) for r in revs] == [(1, "created"), (2, "updated"), (3, "updated")]
    assert revs[1]["changes"] == {
        "label": {"from": "reach", "to": "grasp"},
        "frame_end": {"from": 20, "to": 25},
    }
    assert [r["snapshot"]["label"] for r in revs] == ["reach", "grasp", "pinch"]
    assert [r["actor"]["name"] for r in revs] == ["Ann Otator", "Ann Otator", "Ada Admin"]


def test_no_op_edit_adds_no_revision(client, h, video):
    a = _create(client, h, video)
    res = client.patch(
        f"/api/v1/annotations/{a['id']}", json={"label": "reach", "frame_start": 10}, headers=h
    )
    assert res.json()["revision"] == 1
    assert len(_history(client, h, a["id"])["revisions"]) == 1


def test_mark_for_review(client, h, video):
    a = _create(client, h, video)
    flagged = client.patch(f"/api/v1/annotations/{a['id']}", json={"needs_review": True}, headers=h).json()
    assert flagged["needs_review"] is True
    client.patch(f"/api/v1/annotations/{a['id']}", json={"needs_review": False}, headers=h)
    assert [r["action"] for r in _history(client, h, a["id"])["revisions"]] == [
        "created",
        "flagged",
        "unflagged",
    ]
    assert client.get(_url(video), params={"needs_review": True}, headers=h).json()["total"] == 0


def test_edits_are_validated(client, h, video):
    box = _create(client, h, video, type="bbox", frame_start=1, frame_end=1, data={"box": [0, 0, 0.5, 0.5]})
    url = f"/api/v1/annotations/{box['id']}"
    assert client.patch(url, json={"data": {"box": [0.9, 0.9, 0.5, 0.5]}}, headers=h).status_code == 422
    assert client.patch(url, json={"frame_start": 5}, headers=h).status_code == 422  # start after end
    assert client.patch(url, json={"frame_end": 60_000}, headers=h).status_code == 422
    assert (
        client.patch(f"/api/v1/annotations/{uuid.uuid4()}", json={"label": "x"}, headers=h).status_code == 404
    )


# --- deletes are soft -------------------------------------------------------------------------------


def test_deleting_an_annotation_keeps_it_in_history(client, db, h, video):
    a = _create(client, h, video)
    client.patch(f"/api/v1/annotations/{a['id']}", json={"label": "grasp"}, headers=h)
    res = client.delete(f"/api/v1/annotations/{a['id']}", headers=h)
    assert res.status_code == 200 and res.json()["deleted_at"] is not None

    # Gone from the working views...
    assert client.get(_url(video), headers=h).json()["total"] == 0
    timeline = client.get(f"/api/v1/videos/{video.id}/timeline", headers=h).json()
    assert next(t for t in timeline["tracks"] if t["id"] == "human")["total"] == 0
    # ...but still in the database, with every revision.
    assert db.get(Annotation, uuid.UUID(a["id"])) is not None
    deleted = client.get(_url(video), params={"deleted_only": True}, headers=h).json()
    assert [d["id"] for d in deleted["items"]] == [a["id"]]
    history = _history(client, h, a["id"])
    assert [r["action"] for r in history["revisions"]] == ["created", "updated", "deleted"]
    assert history["revisions"][0]["snapshot"]["label"] == "reach"
    assert history["annotation"]["deleted_at"] is not None

    assert client.patch(f"/api/v1/annotations/{a['id']}", json={"label": "x"}, headers=h).status_code == 409
    restored = client.post(f"/api/v1/annotations/{a['id']}/restore", headers=h).json()
    assert restored["deleted_at"] is None and restored["label"] == "grasp"
    assert [r["action"] for r in _history(client, h, a["id"])["revisions"]][-1] == "restored"
    assert client.get(_url(video), headers=h).json()["total"] == 1
    assert db.scalar(
        select(AnnotationRevision.id).where(AnnotationRevision.annotation_id == uuid.UUID(a["id"]))
    )


# --- AI annotations: corrections keep the prediction ------------------------------------------------


def test_correcting_an_ai_annotation_keeps_the_prediction(client, db, h, video):
    prediction = _auto(db, video)
    res = client.patch(f"/api/v1/annotations/{prediction.id}", json={"data": {"box": [0.1, 0.1, 0.3, 0.3]}},
                       headers=h)  # fmt: skip
    assert res.status_code == 200, res.text
    fix = res.json()
    assert fix["id"] != str(prediction.id)
    assert (fix["source"], fix["parent_annotation_id"], fix["confidence"]) == (
        "auto_corrected",
        str(prediction.id),
        None,
    )
    assert fix["model_version_id"] == str(prediction.model_version_id)

    db.expire_all()
    original = db.get(Annotation, prediction.id)
    assert original.data == {"box": [0.1, 0.1, 0.2, 0.2]} and original.confidence == 0.83  # untouched
    assert original.superseded_at is not None
    listed = client.get(_url(video), headers=h).json()["items"]
    assert [a["id"] for a in listed] == [fix["id"]]  # the correction replaces it in the working view
    with_old = client.get(_url(video), params={"include_superseded": True}, headers=h).json()
    assert with_old["total"] == 2

    history = _history(client, h, prediction.id)
    assert [r["action"] for r in history["revisions"]] == ["superseded"]
    assert [c["id"] for c in history["corrections"]] == [fix["id"]]
    fix_history = _history(client, h, fix["id"])
    assert fix_history["parent"]["id"] == str(prediction.id)
    assert fix_history["revisions"][0]["changes"]["data"]["from"] == {"box": [0.1, 0.1, 0.2, 0.2]}

    # The superseded prediction can't be edited again; its correction can.
    assert (
        client.patch(f"/api/v1/annotations/{prediction.id}", json={"label": "x"}, headers=h).status_code
        == 409
    )
    assert (
        client.patch(f"/api/v1/annotations/{fix['id']}", json={"label": "left hand"}, headers=h).json()["id"]
        == fix["id"]
    )


def test_flagging_an_ai_annotation_is_not_a_correction(client, db, h, video):
    prediction = _auto(db, video)
    res = client.patch(f"/api/v1/annotations/{prediction.id}", json={"needs_review": True}, headers=h).json()
    assert res["id"] == str(prediction.id) and res["source"] == "auto" and res["needs_review"] is True


# --- timeline ---------------------------------------------------------------------------------------


def test_timeline_tracks(client, db, h, video):
    human = _create(client, h, video, frame_start=100, frame_end=200)
    _auto(db, video, category="hand", frame_start=150, frame_end=150)
    _auto(
        db, video, category="movement", type="segment", data={}, label="reach", frame_start=300, frame_end=360
    )
    _auto(
        db,
        video,
        category="general",
        type="segment",
        data={},
        label="scene",
        frame_start=5000,
        frame_end=6000,
    )

    tl = client.get(f"/api/v1/videos/{video.id}/timeline", headers=h).json()
    assert (tl["frame_from"], tl["frame_to"]) == (0, 53_999)
    tracks = {t["id"]: t for t in tl["tracks"]}
    assert list(tracks) == ["hand", "finger", "object", "movement", "human", "ai", "pipeline"]
    assert {k: t["total"] for k, t in tracks.items()} == {
        "hand": 1, "finger": 0, "object": 0, "movement": 1, "human": 1, "ai": 1, "pipeline": 0,
    }  # fmt: skip
    assert tracks["human"]["segments"][0]["id"] == human["id"]
    assert tracks["hand"]["segments"][0]["confidence"] == 0.83
    assert tracks["pipeline"] == {"id": "pipeline", "label": "Pipeline events", "kind": "event", "total": 0,
                                  "segments": [], "buckets": None, "filled_from_phase": 7}  # fmt: skip

    window = client.get(f"/api/v1/videos/{video.id}/timeline", params={"frame_from": 180, "frame_to": 320},
                        headers=h).json()  # fmt: skip
    totals = {t["id"]: t["total"] for t in window["tracks"]}
    assert (totals["human"], totals["hand"], totals["movement"], totals["ai"]) == (1, 0, 1, 0)
    bad = client.get(
        f"/api/v1/videos/{video.id}/timeline", params={"frame_from": 10, "frame_to": 5}, headers=h
    )
    assert bad.status_code == 422


def test_busy_tracks_come_back_as_density_buckets(client, db, h, video, annotator):
    # 30 minutes of per-frame hand detections is far too many segments to draw.
    model = ModelVersion(name="hands", version="1", kind="hand_tracking", adapter="x")
    db.add(model)
    db.flush()
    rows = [dict(video_id=video.id, type="bbox", label="hand", category="hand", frame_start=f, frame_end=f,
                 data={"box": [0, 0, 0.1, 0.1]}, source="auto", confidence=0.9, model_version_id=model.id)
            for f in range(0, 54_000, 2)]  # fmt: skip
    db.execute(insert(Annotation), rows)
    db.commit()

    tl = client.get(f"/api/v1/videos/{video.id}/timeline", params={"buckets": 100}, headers=h).json()
    hand = next(t for t in tl["tracks"] if t["id"] == "hand")
    assert hand["total"] == 27_000 and hand["segments"] is None
    assert len(hand["buckets"]) == 100
    assert sum(b["count"] for b in hand["buckets"]) == 27_000
    assert hand["buckets"][0] == {"start": 0, "end": 539, "count": 270}
    assert hand["buckets"][-1]["end"] == 53_999

    # Zoomed in, the same track has few enough to draw one by one.
    zoom = client.get(f"/api/v1/videos/{video.id}/timeline", params={"frame_from": 1000, "frame_to": 1099},
                      headers=h).json()  # fmt: skip
    hand = next(t for t in zoom["tracks"] if t["id"] == "hand")
    assert hand["total"] == 50 and len(hand["segments"]) == 50 and hand["buckets"] is None


def test_next_and_previous_event(client, h, video):
    for start in (50, 10, 300):
        _create(client, h, video, frame_start=start, frame_end=start + 5)
    url = _url(video, "/adjacent")
    assert client.get(url, params={"frame": 10}, headers=h).json()["frame"] == 50
    assert client.get(url, params={"frame": 50, "direction": "next"}, headers=h).json()["frame"] == 300
    assert client.get(url, params={"frame": 300}, headers=h).json() == {"frame": None, "annotation_id": None}
    assert client.get(url, params={"frame": 50, "direction": "prev"}, headers=h).json()["frame"] == 10
    assert client.get(url, params={"frame": 10, "direction": "prev"}, headers=h).json()["frame"] is None


def test_list_filters_and_labels(client, h, video):
    _create(client, h, video, label="reach", frame_start=0, frame_end=10)
    _create(client, h, video, label="reach", frame_start=100, frame_end=110)
    _create(
        client, h, video, type="bbox", label="mug", frame_start=50, frame_end=50, data={"box": [0, 0, 1, 1]}
    )
    in_window = client.get(_url(video), params={"frame_from": 5, "frame_to": 60}, headers=h).json()
    assert [a["label"] for a in in_window["items"]] == ["reach", "mug"]
    assert client.get(_url(video), params={"type": "bbox"}, headers=h).json()["total"] == 1
    assert client.get(_url(video), params={"q": "rea"}, headers=h).json()["total"] == 2
    paged = client.get(_url(video), params={"limit": 1, "offset": 1}, headers=h).json()
    assert paged["total"] == 3 and [a["label"] for a in paged["items"]] == ["mug"]
    labels = client.get("/api/v1/annotations/labels", headers=h).json()
    assert labels == [{"label": "reach", "count": 2}, {"label": "mug", "count": 1}]
    assert client.get(f"/api/v1/videos/{uuid.uuid4()}/annotations", headers=h).status_code == 404
