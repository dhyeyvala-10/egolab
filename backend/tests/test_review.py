"""
Review and active learning (spec Phase 5).

Acceptance:
- "Correcting an event creates a new version and keeps the old one": a correction is a new event (and
  timeline segment) whose parent is the prediction; the prediction stays, marked corrected.
- "The queue order visibly changes when confidence data changes": a new classification of the same video
  with different confidences reorders the queue.
"""

import uuid

import pytest
from sqlalchemy import select

from egolabs.models import Annotation, CvRun, MovementEvent, MovementEventReview
from tests import reviewgen as rg
from tests.conftest import auth_header, drain, user_with_role

Q = "/api/v1/review"


@pytest.fixture
def h(admin):
    return auth_header(admin)


def _queue(client, h, **params) -> list[dict]:
    res = client.get(f"{Q}/queue", params={"limit": 200, **params}, headers=h)
    assert res.status_code == 200, res.text
    return res.json()["items"]


def _order(items: list[dict]) -> list[tuple[str, int]]:
    return [(i["movement_class"]["name"], i["start_frame"]) for i in items]


# --- acceptance --------------------------------------------------------------------------------------


def test_correcting_an_event_creates_a_new_version_and_keeps_the_old_one(client, db, h):
    v = rg.video(db)
    _, (grasp, _) = rg.movement_run(
        db, v, [rg.Ev("grasp", 10, 40, 0.8, obj="cup"), rg.Ev("hold", 41, 90, 0.9)]
    )
    res = client.post(f"{Q}/events/{grasp.id}/correct",
                      json={"class": "pinch", "start_frame": 12, "end_frame": 38, "clear_object": True}, headers=h)  # fmt: skip
    assert res.status_code == 201, res.text
    new = res.json()["event"]
    assert new["id"] != str(grasp.id) and res.json()["parent_event_id"] == str(grasp.id)
    assert new["source"] == "auto_corrected" and new["status"] == "confirmed" and new["confidence"] is None
    assert new["movement_class"]["name"] == "pinch" and (new["start_frame"], new["end_frame"]) == (12, 38)
    assert new["object_label"] is None and new["model_version"]["id"] == str(grasp.model_version_id)

    # The prediction is untouched apart from being marked corrected.
    old = client.get(f"/api/v1/movement/events/{grasp.id}", headers=h).json()
    assert old["status"] == "corrected" and old["superseded_at"]
    assert old["movement_class"]["name"] == "grasp" and (old["start_frame"], old["end_frame"]) == (10, 40)
    assert old["confidence"] == 0.8 and old["object_label"] == "cup"

    # Each version has its own segment: the correction's parent is the prediction's.
    db.expire_all()
    pred_ann = db.get(Annotation, grasp.annotation_id)
    new_ann = db.get(Annotation, uuid.UUID(new["annotation_id"]))
    assert pred_ann.superseded_at is not None and pred_ann.label == "Grasp · cup"
    assert (
        new_ann.parent_annotation_id == pred_ann.id
        and new_ann.source == "auto_corrected"
        and new_ann.label == "Pinch"
    )

    hist = client.get(f"{Q}/events/{new['id']}/history", headers=h).json()
    assert [(x["source"], x["movement_class"]["name"], x["status"]) for x in hist["versions"]] == [
        ("auto", "grasp", "corrected"), ("auto_corrected", "pinch", "confirmed")]  # fmt: skip
    assert {(x["method"], x["to_status"]) for x in hist["log"]} == {
        ("correction", "corrected"),
        ("correction", "confirmed"),
    }

    # Current views show the correction in place of the prediction; the prediction is still listed by run.
    events = client.get("/api/v1/movement/events", params={"video_id": str(v.id)}, headers=h).json()["items"]
    assert sorted(e["movement_class"]["name"] for e in events) == ["hold", "pinch"]
    by_run = client.get("/api/v1/movement/events", params={"run_id": str(grasp.run_id)}, headers=h).json()[
        "items"
    ]
    assert {e["id"] for e in by_run} >= {str(grasp.id), new["id"]}
    timeline = client.get(
        f"/api/v1/videos/{v.id}/annotations", params={"category": "movement"}, headers=h
    ).json()
    assert sorted(a["label"] for a in timeline["items"]) == ["Hold", "Pinch"]

    # A correction can't be re-corrected through the prediction.
    again = client.post(f"{Q}/events/{grasp.id}/correct", json={"class": "tap"}, headers=h)
    assert again.status_code == 409


def test_the_queue_reorders_when_confidence_data_changes(client, db, h):
    v = rg.video(db)
    plan = [("grasp", 10, 40), ("release", 100, 120), ("pinch", 200, 230)]
    rg.movement_run(
        db, v, [rg.Ev(c, s, e, conf) for (c, s, e), conf in zip(plan, (0.9, 0.7, 0.8), strict=True)]
    )
    first = _order(_queue(client, h, sort="confidence"))
    assert first == [("release", 100), ("pinch", 200), ("grasp", 10)]  # lowest confidence first
    # A new classification of the video (another model version) with different confidences.
    rg.movement_run(db, v, [rg.Ev(c, s, e, conf) for (c, s, e), conf in zip(plan, (0.65, 0.95, 0.75), strict=True)],
                    mv=rg.model_version(db, config={"pinch_ratio": 0.3}))  # fmt: skip
    second = _order(_queue(client, h, sort="confidence"))
    assert second == [("grasp", 10), ("pinch", 200), ("release", 100)]
    # The combined priority moves the same way.
    items = _queue(client, h)
    assert items[0]["movement_class"]["name"] == "grasp"
    assert items[0]["priority"] >= items[1]["priority"] >= items[2]["priority"]


# --- the queue ---------------------------------------------------------------------------------------


def test_priority_combines_confidence_disagreement_and_rarity(client, db, h):
    v = rg.video(db)
    common = [rg.Ev("hold", 10 + 20 * i, 25 + 20 * i, 0.8) for i in range(8)]
    rare = rg.Ev("pinch", 400, 420, 0.8)
    rg.movement_run(db, v, [*common, rare])
    items = _queue(client, h)
    # Same confidence, no second model: the rare class comes first, and the parts add up.
    assert items[0]["movement_class"]["name"] == "pinch" and items[0]["rarity"] == 1.0
    assert all(i["movement_class"]["name"] == "hold" and i["rarity"] == 0.0 for i in items[1:])
    parts = items[0]["priority_parts"]
    assert items[0]["priority"] == pytest.approx(
        parts["confidence"] + parts["disagreement"] + parts["rarity"], abs=1e-3
    )
    assert items[0]["disagreement"] is None and items[0]["compared_versions"] == 0
    assert _order(_queue(client, h, sort="rarity"))[0] == ("pinch", 400)


def test_disagreement_between_model_versions(client, db, h):
    v = rg.video(db)
    rg.movement_run(db, v, [rg.Ev("grasp", 10, 40, 0.8), rg.Ev("hold", 50, 90, 0.8)])
    _, events = rg.movement_run(
        db,
        v,
        [rg.Ev("grasp", 10, 40, 0.8), rg.Ev("hold", 70, 110, 0.8), rg.Ev("tap", 200, 205, 0.8)],
        mv=rg.model_version(db, config={"other": 1}),
    )
    db.expire_all()
    got = {e.start_frame: db.get(MovementEvent, e.id) for e in events}
    assert got[10].disagreement == 0.0  # the same event
    assert got[70].disagreement == pytest.approx(1 - 21 / 61, abs=1e-3)  # overlaps 70–90 of 50–110
    assert got[200].disagreement == 1.0  # the other model never saw it
    assert {e.compared_versions for e in got.values()} == {1}
    assert _order(_queue(client, h, sort="disagreement"))[0] == ("tap", 200)


def test_queue_filters_by_class_object_and_status(client, db, h):
    v = rg.video(db)
    _, evs = rg.movement_run(db, v, [rg.Ev("grasp", 10, 40, 0.8, obj="cup"), rg.Ev("grasp", 100, 140, 0.5, obj="phone"),
                                    rg.Ev("point", 200, 240, 0.9)])  # fmt: skip
    assert len(_queue(client, h, **{"class": "grasp"})) == 2
    assert [i["object_label"] for i in _queue(client, h, object_label="phone")] == ["phone"]
    assert [i["movement_class"]["name"] for i in _queue(client, h, no_object=True)] == ["point"]
    assert [i["status"] for i in _queue(client, h, status="needs_review")] == ["needs_review"]
    client.post(f"{Q}/events/{evs[0].id}/status", json={"status": "confirmed"}, headers=h)
    assert len(_queue(client, h)) == 2  # reviewed events leave the pending queue


# --- summaries ---------------------------------------------------------------------------------------


def test_summary_by_class_and_by_object(client, db, h):
    v = rg.video(db)
    _, evs = rg.movement_run(db, v, [rg.Ev("grasp", 10, 40, 0.8, obj="cup"), rg.Ev("grasp", 100, 140, 0.5, obj="cup"),
                                    rg.Ev("point", 200, 240, 0.9)])  # fmt: skip
    client.post(f"{Q}/events/{evs[0].id}/status", json={"status": "confirmed"}, headers=h)
    client.post(f"{Q}/events/{evs[2].id}/correct", json={"class": "gesture"}, headers=h)
    by_class = client.get(f"{Q}/summary", headers=h).json()
    g = {x["key"]: x for x in by_class["groups"]}
    assert (
        g["grasp"]["total"],
        g["grasp"]["pending"],
        g["grasp"]["confirmed"],
        g["grasp"]["needs_review"],
    ) == (2, 1, 1, 1)
    assert g["grasp"]["min_confidence"] == 0.5 and g["point"]["corrected"] == 1
    assert "gesture" not in g  # a correction isn't counted as another prediction
    assert by_class["totals"]["total"] == 3
    by_object = client.get(f"{Q}/summary", params={"group": "object"}, headers=h).json()
    assert {x["label"]: x["total"] for x in by_object["groups"]} == {"cup": 2, "No object": 1}


# --- reviewing ---------------------------------------------------------------------------------------


def test_review_statuses_keep_the_segment_in_step_and_are_logged(client, db, h, admin):
    v = rg.video(db)
    _, (e, low) = rg.movement_run(db, v, [rg.Ev("grasp", 10, 40, 0.8), rg.Ev("tap", 60, 62, 0.4)])
    assert (
        client.post(f"{Q}/events/{e.id}/status", json={"status": "rejected"}, headers=h).json()["event"][
            "status"
        ]
        == "rejected"
    )
    db.expire_all()
    assert db.get(Annotation, e.annotation_id).deleted_at is not None
    assert (
        client.post(f"{Q}/events/{e.id}/status", json={"status": "confirmed"}, headers=h).status_code == 200
    )
    db.expire_all()
    assert db.get(Annotation, e.annotation_id).deleted_at is None
    res = client.post(f"{Q}/events/{low.id}/status", json={"status": "confirmed"}, headers=h).json()["event"]
    assert (
        res["status"] == "confirmed"
        and res["annotation"]["needs_review"] is False
        and res["review_method"] == "individual"
    )
    log = db.scalars(select(MovementEventReview).where(MovementEventReview.event_id == e.id)
                     .order_by(MovementEventReview.created_at)).all()  # fmt: skip
    assert [(r.from_status, r.to_status, r.method) for r in log] == [
        ("auto_detected", "rejected", "individual"), ("rejected", "confirmed", "individual")]  # fmt: skip
    assert all(str(r.actor_id) == admin["user"]["id"] for r in log)


def test_inspector_correction_is_a_new_event_version(client, db, h):
    v = rg.video(db)
    _, (e,) = rg.movement_run(db, v, [rg.Ev("grasp", 10, 40, 0.8)])
    res = client.patch(
        f"/api/v1/annotations/{e.annotation_id}", json={"label": "Release", "frame_end": 30}, headers=h
    )
    assert res.status_code == 200, res.text
    db.expire_all()
    versions = db.scalars(
        select(MovementEvent).where(MovementEvent.video_id == v.id).order_by(MovementEvent.created_at)
    ).all()
    assert len(versions) == 2
    pred, fix = versions
    assert pred.status == "corrected" and pred.superseded_at is not None
    assert fix.parent_event_id == pred.id and fix.end_frame == 30 and fix.status == "confirmed"
    names = client.get(f"/api/v1/movement/events/{fix.id}", headers=h).json()["movement_class"]["name"]
    assert names == "release"
    # Editing the correction again edits that version in place (its segment keeps every revision).
    client.patch(f"/api/v1/annotations/{fix.annotation_id}", json={"frame_start": 12}, headers=h)
    db.expire_all()
    assert db.get(MovementEvent, fix.id).start_frame == 12
    assert db.scalar(select(MovementEvent).where(MovementEvent.parent_event_id == fix.id)) is None


def test_viewers_cannot_review_and_annotators_cannot_bulk(client, db, admin, viewer):
    v = rg.video(db)
    _, (e,) = rg.movement_run(db, v, [rg.Ev("grasp", 10, 40, 0.8)])
    vh = auth_header(viewer)
    assert (
        client.post(f"{Q}/events/{e.id}/status", json={"status": "confirmed"}, headers=vh).status_code == 403
    )
    assert client.post(f"{Q}/events/{e.id}/correct", json={"class": "tap"}, headers=vh).status_code == 403
    ah = auth_header(user_with_role(client, admin, "ann@example.com", "annotator"))
    assert (
        client.post(f"{Q}/events/{e.id}/status", json={"status": "confirmed"}, headers=ah).status_code == 200
    )
    body = {"filters": {}, "action": "confirmed"}
    assert client.post(f"{Q}/bulk", json=body, headers=ah).status_code == 403
    assert client.post(f"{Q}/rules", json={"min_confidence": 0.9}, headers=ah).status_code == 403


# --- bulk review ---------------------------------------------------------------------------------------


def test_bulk_accept_preview_apply_and_undo(client, db, h):
    s = rg.session(db)
    v = rg.video(db, session_id=s.id)
    other = rg.video(db, name="other.mp4")
    _, evs = rg.movement_run(
        db, v, [rg.Ev("grasp", 10, 40, 0.8), rg.Ev("grasp", 100, 140, 0.5), rg.Ev("point", 200, 240, 0.9)]
    )
    rg.movement_run(db, other, [rg.Ev("grasp", 10, 40, 0.8)])
    body = {"filters": {"session_id": str(s.id), "classes": ["grasp"]}, "action": "confirmed"}
    preview = client.post(f"{Q}/bulk/preview", json=body, headers=h).json()
    assert preview["count"] == 2 and preview["by_class"] == {"grasp": 2} and not preview["over_limit"]
    assert len(preview["sample"]) == 2
    # Someone reviews one of them first: bulk only touches pending events.
    client.post(f"{Q}/events/{evs[1].id}/status", json={"status": "rejected"}, headers=h)
    batch = client.post(f"{Q}/bulk", json=body, headers=h).json()
    assert batch["count"] == 1 and batch["method"] == "bulk"
    db.expire_all()
    assert (db.get(MovementEvent, evs[0].id).status, db.get(MovementEvent, evs[0].id).review_method) == (
        "confirmed",
        "bulk",
    )
    assert db.get(MovementEvent, evs[2].id).status == "auto_detected"

    undone = client.post(f"{Q}/batches/{batch['id']}/undo", json={}, headers=h).json()
    assert undone["undone_count"] == 1 and undone["undone_at"]
    db.expire_all()
    assert db.get(MovementEvent, evs[0].id).status == "auto_detected"
    assert db.get(MovementEvent, evs[1].id).status == "rejected"  # not the batch's
    assert client.post(f"{Q}/batches/{batch['id']}/undo", json={}, headers=h).status_code == 409


def test_bulk_reject_and_undo_restores_segments(client, db, h):
    v = rg.video(db)
    _, evs = rg.movement_run(
        db, v, [rg.Ev("tap", 10, 12, 0.3), rg.Ev("tap", 30, 32, 0.4), rg.Ev("grasp", 50, 90, 0.9)]
    )
    body = {"filters": {"video_id": str(v.id), "max_confidence": 0.5}, "action": "rejected"}
    batch = client.post(f"{Q}/bulk", json=body, headers=h).json()
    assert batch["count"] == 2
    timeline = client.get(
        f"/api/v1/videos/{v.id}/annotations", params={"category": "movement"}, headers=h
    ).json()
    assert [a["label"] for a in timeline["items"]] == ["Grasp"]
    # One of them is reviewed again after the batch: undo leaves it.
    client.post(f"{Q}/events/{evs[0].id}/status", json={"status": "needs_review"}, headers=h)
    assert client.post(f"{Q}/batches/{batch['id']}/undo", headers=h).json()["undone_count"] == 1
    db.expire_all()
    assert (
        db.get(MovementEvent, evs[1].id).status == "needs_review"
    )  # back where it was (flagged, low confidence)
    assert db.get(Annotation, evs[1].annotation_id).deleted_at is None
    assert db.get(MovementEvent, evs[0].id).status == "needs_review"
    listed = client.get(f"{Q}/batches", headers=h).json()
    assert listed["total"] == 1 and listed["items"][0]["undone_count"] == 1


def test_bulk_selection_by_ids_and_the_limit(client, db, h, monkeypatch):
    v = rg.video(db)
    _, evs = rg.movement_run(db, v, [rg.Ev("hold", 10 * i, 10 * i + 5, 0.8) for i in range(5)])
    ids = [str(evs[1].id), str(evs[3].id)]
    batch = client.post(
        f"{Q}/bulk", json={"filters": {"event_ids": ids}, "action": "confirmed"}, headers=h
    ).json()
    assert batch["count"] == 2
    from egolabs.config import get_settings

    monkeypatch.setattr(get_settings(), "review_bulk_max", 2)
    body = {"filters": {"video_id": str(v.id)}, "action": "confirmed"}
    assert client.post(f"{Q}/bulk/preview", json=body, headers=h).json()["over_limit"] is True
    assert client.post(f"{Q}/bulk", json=body, headers=h).status_code == 409


# --- auto-accept rules -------------------------------------------------------------------------------


def test_auto_accept_rules_on_new_predictions(client, db, h):
    assert client.post(f"{Q}/rules", json={"min_confidence": 0.85}, headers=h).status_code == 201
    pinch = client.post(f"{Q}/rules", json={"class": "pinch", "min_confidence": 0.95}, headers=h).json()
    off = client.post(f"{Q}/rules", json={"class": "tap", "min_confidence": 0.1, "enabled": False}, headers=h)
    assert off.status_code == 201
    assert (
        client.post(f"{Q}/rules", json={"class": "pinch", "min_confidence": 0.5}, headers=h).status_code
        == 409
    )
    v = rg.video(db)
    run, evs = rg.movement_run(db, v, [
        rg.Ev("grasp", 10, 40, 0.9),   # default rule: accepted
        rg.Ev("grasp", 50, 80, 0.8),   # below the default
        rg.Ev("pinch", 100, 110, 0.9),  # below pinch's own threshold
        rg.Ev("pinch", 120, 130, 0.97),  # accepted by pinch's rule
        rg.Ev("tap", 140, 142, 0.99),  # tap opted out (rule off)
    ])  # fmt: skip
    db.expire_all()
    got = [(db.get(MovementEvent, e.id).status, db.get(MovementEvent, e.id).review_method) for e in evs]
    assert got == [("confirmed", "auto_rule"), ("auto_detected", None), ("auto_detected", None),
                   ("confirmed", "auto_rule"), ("auto_detected", None)]  # fmt: skip
    assert db.get(CvRun, run.id).stats["auto_accepted"] == 2
    assert db.get(MovementEvent, evs[3].id).review_rule_id == uuid.UUID(pinch["id"])
    assert db.get(MovementEvent, evs[3].id).reviewed_by is None  # no person involved
    rules = client.get(f"{Q}/rules", headers=h).json()
    assert rules[0]["movement_class"] is None and {
        r["accepted"] for r in rules if r["movement_class"] and r["movement_class"]["name"] == "pinch"
    } == {1}


def test_flagged_events_are_never_auto_accepted(client, db, h):
    client.post(f"{Q}/rules", json={"min_confidence": 0.0}, headers=h)
    v = rg.video(db)
    _, (low, ok) = rg.movement_run(db, v, [rg.Ev("tap", 10, 12, 0.4), rg.Ev("grasp", 20, 40, 0.7)])
    db.expire_all()
    assert db.get(MovementEvent, low.id).status == "needs_review"
    assert db.get(MovementEvent, ok.id).status == "confirmed"


def test_applying_rules_to_existing_predictions_is_an_undoable_batch(client, db, h):
    v = rg.video(db)
    _, evs = rg.movement_run(
        db, v, [rg.Ev("grasp", 10, 40, 0.9), rg.Ev("hold", 50, 90, 0.7), rg.Ev("tap", 95, 97, 0.95)]
    )
    client.post(f"{Q}/rules", json={"min_confidence": 0.85}, headers=h)
    preview = client.post(f"{Q}/rules/apply/preview", json={}, headers=h).json()
    assert preview["count"] == 2 and preview["by_class"] == {"grasp": 1, "tap": 1}
    batch = client.post(f"{Q}/rules/apply", json={}, headers=h).json()
    assert batch["count"] == 2 and batch["method"] == "auto_rule"
    db.expire_all()
    assert db.get(MovementEvent, evs[0].id).review_method == "auto_rule"
    client.post(f"{Q}/batches/{batch['id']}/undo", headers=h)
    db.expire_all()
    assert {db.get(MovementEvent, e.id).status for e in evs} == {"auto_detected"}


# --- metrics -----------------------------------------------------------------------------------------


def test_metrics_correction_rate_accuracy_and_throughput(client, db, h, admin):
    client.post(f"{Q}/rules", json={"class": "hold", "min_confidence": 0.9}, headers=h)
    v = rg.video(db)
    _, evs = rg.movement_run(db, v, [rg.Ev("grasp", 10, 40, 0.8), rg.Ev("grasp", 50, 80, 0.8), rg.Ev("grasp", 90, 120, 0.8),
                                    rg.Ev("grasp", 130, 160, 0.8), rg.Ev("hold", 170, 200, 0.95)])  # fmt: skip
    ah = auth_header(user_with_role(client, admin, "ann@example.com", "annotator", name="Ann"))
    client.post(f"{Q}/events/{evs[0].id}/status", json={"status": "confirmed"}, headers=ah)
    client.post(f"{Q}/events/{evs[1].id}/status", json={"status": "confirmed"}, headers=ah)
    client.post(f"{Q}/events/{evs[2].id}/correct", json={"class": "pinch"}, headers=ah)
    client.post(f"{Q}/events/{evs[3].id}/status", json={"status": "rejected"}, headers=h)
    m = client.get(f"{Q}/metrics", headers=h).json()
    assert (
        m["predictions"],
        m["human_reviewed"],
        m["confirmed"],
        m["corrected"],
        m["rejected"],
        m["auto_accepted"],
    ) == (5, 4, 2, 1, 1, 1)
    assert m["correction_rate"] == 0.25 and m["rejection_rate"] == 0.25 and m["pending"] == 0
    per = {c["movement_class"]["name"]: c for c in m["per_class"]}
    assert per["grasp"]["accuracy"] == 0.5 and per["grasp"]["human_reviewed"] == 4
    assert (
        per["hold"]["accuracy"] is None and per["hold"]["auto_accepted"] == 1
    )  # auto-accepts aren't ground truth
    people = {a["user"]["name"]: a for a in m["annotators"]}
    assert (people["Ann"]["individual"], people["Ann"]["corrections"], people["Ann"]["confirmed"]) == (
        2,
        1,
        2,
    )
    assert people["Ann"]["active_hours"] == 1 and people["Ann"]["per_hour"] == 3.0
    assert people["Ada Admin"]["rejected"] == 1
    assert sum(d["human"] for d in m["daily"]) == 5 and sum(d["auto_rule"] for d in m["daily"]) == 1
    # Undoing a bulk review takes it back; it isn't more reviewing.
    b = client.post(
        f"{Q}/bulk",
        json={"filters": {"event_ids": [str(evs[4].id)], "statuses": ["confirmed"]}, "action": "rejected"},
        headers=h,
    ).json()
    assert b["count"] == 0  # bulk only changes pending events
    v2 = rg.video(db, name="more.mp4")
    _, (extra,) = rg.movement_run(db, v2, [rg.Ev("tap", 5, 8, 0.7)])
    b = client.post(
        f"{Q}/bulk", json={"filters": {"event_ids": [str(extra.id)]}, "action": "confirmed"}, headers=h
    ).json()
    client.post(f"{Q}/batches/{b['id']}/undo", headers=h)
    m2 = client.get(f"{Q}/metrics", headers=h).json()
    admin_row = next(a for a in m2["annotators"] if a["user"]["name"] == "Ada Admin")
    assert (
        admin_row["reviews"] == 2 and admin_row["bulk"] == 1
    )  # the reject and the bulk accept, not the undo
    assert sum(d["human"] for d in m2["daily"]) == 6


# --- auto annotation ---------------------------------------------------------------------------------


def test_auto_annotate_sessions_with_a_chosen_model_version(client, db, h, enqueued):
    s = rg.session(db)
    ready = rg.video(db, name="a.mp4", session_id=s.id)
    rg.movement_run(
        db, ready, [rg.Ev("grasp", 10, 40, 0.8)], mv=rg.model_version(db, config={"pinch_ratio": 0.3})
    )
    rg.video(db, name="b.mp4", session_id=s.id)  # ready, but never hand-tracked: nothing to classify
    rg.video(db, name="c.mp4", session_id=s.id, status="processing")
    versions = client.get(f"{Q}/model-versions", params={"kind": "movement"}, headers=h).json()
    chosen = next(x for x in versions if x["config"] == {"pinch_ratio": 0.3})
    assert chosen["runs"] == 1 and chosen["configured"] is False
    res = client.post(f"{Q}/auto-annotate", json={"session_ids": [str(s.id)], "kinds": ["movement"],
                                                 "models": {"movement": {"model_version_id": chosen["id"]}}}, headers=h)  # fmt: skip
    assert res.status_code == 201, res.text
    out = res.json()
    assert out["videos"] == 1 and [r["video"]["name"] for r in out["runs"]] == ["a.mp4"]
    assert {x["video"]["name"]: x["reason"] for x in out["skipped"]}.keys() == {"b.mp4", "c.mp4"}
    assert out["setups"] == {"movement": {"adapter": "rules", "config": {"pinch_ratio": 0.3}}}
    run = db.get(CvRun, uuid.UUID(out["runs"][0]["id"]))
    assert (run.adapter, run.config, run.status) == ("rules", {"pinch_ratio": 0.3}, "queued")
    assert len(enqueued) == 1


def test_auto_annotate_rejects_stubs_and_wrong_kinds(client, db, h):
    s = rg.session(db)
    rg.video(db, session_id=s.id)
    hand_mv = rg.model_version(db, "hand_tracking", name="mediapipe-hands")
    bad = client.post(f"{Q}/auto-annotate", json={"session_ids": [str(s.id)],
                                                 "models": {"movement": {"model_version_id": str(hand_mv.id)}}}, headers=h)  # fmt: skip
    assert bad.status_code == 422
    stub = client.post(f"{Q}/auto-annotate", json={"session_ids": [str(s.id)],
                                                  "models": {"object_detection": {"adapter": "yolo-objects"}}}, headers=h)  # fmt: skip
    assert stub.status_code == 422 and "stub" in stub.json()["detail"]
    nothing = client.post(f"{Q}/auto-annotate", json={}, headers=h)
    assert nothing.status_code == 422


def test_auto_annotate_with_an_adapter_and_config(client, db, h, enqueued):
    """An adapter and config instead of a registered version: the run gets exactly that setup."""
    s = rg.session(db)
    v = rg.video(db, session_id=s.id)
    _, first = rg.movement_run(db, v, [rg.Ev("grasp", 10, 40, 0.8)])
    res = client.post(f"{Q}/auto-annotate", json={"video_ids": [str(v.id)], "kinds": ["movement"],
                                                 "models": {"movement": {"adapter": "events-file", "config": {}}}}, headers=h)  # fmt: skip
    assert res.status_code == 201, res.text
    assert res.json()["runs"][0]["adapter"] == "events-file"
    drain(enqueued)  # events-file with no source configured: the run fails with the reason
    run = db.get(CvRun, uuid.UUID(res.json()["runs"][0]["id"]))
    db.refresh(run)
    assert run.status == "failed" and run.error
    assert db.get(MovementEvent, first[0].id).status == "auto_detected"


def test_moving_a_video_to_a_session_moves_its_events(client, db, h):
    v = rg.video(db)
    _, (e,) = rg.movement_run(db, v, [rg.Ev("grasp", 10, 40, 0.8)])
    s = rg.session(db)
    assert (
        client.patch(f"/api/v1/videos/{v.id}", json={"session_id": str(s.id)}, headers=h).status_code == 200
    )
    assert [i["id"] for i in _queue(client, h, session_id=str(s.id))] == [str(e.id)]
