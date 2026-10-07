"""
Dataset versions (spec Phase 6), on stored events with exact inputs (`tests/reviewgen.py`).

Acceptance:
- "Rebuilding a dataset version from its recorded spec gives an identical hash": a check rebuilds the version
  from its recorded spec and pinned inputs after the data has changed (more reviews, a correction, a new
  model run) and gets the same hash; building a new version from the same spec now does not.
- "Lineage view reaches the raw file from any sample": every sample's lineage graph reaches its raw file,
  through its annotation, event, runs, model versions, and video.
"""

import uuid

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError

from egolabs.models import Dataset, DatasetVersion, DatasetVersionSample, Device, Operator
from tests import reviewgen as rg
from tests.conftest import auth_header, drain

D = "/api/v1/datasets"


@pytest.fixture
def h(admin):
    return auth_header(admin)


def _dataset(client, h, name="grasps") -> str:
    res = client.post(D, json={"name": name}, headers=h)
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _build(client, h, enqueued, dataset_id, **spec) -> dict:
    res = client.post(f"{D}/{dataset_id}/versions", json={"spec": spec}, headers=h)
    assert res.status_code == 202, res.text
    drain(enqueued)
    v = client.get(f"{D}/versions/{res.json()['id']}", headers=h).json()
    assert v["status"] == "ready", v["error"]
    return v


def _samples(client, h, version_id) -> list[dict]:
    return client.get(f"{D}/versions/{version_id}/samples", params={"limit": 500}, headers=h).json()["items"]


def _check(client, h, enqueued, version_id) -> dict:
    res = client.post(f"{D}/versions/{version_id}/checks", headers=h)
    assert res.status_code == 202, res.text
    drain(enqueued)
    return client.get(f"{D}/versions/{version_id}/checks", headers=h).json()[0]


def _world(db):
    """Two sessions (one per operator), a video each, one classification run each."""
    op1, op2 = Operator(name="Op One"), Operator(name="Op Two")
    dev = Device(name="Head cam")
    db.add_all([op1, op2, dev])
    db.commit()
    s1 = rg.session(db, "SESSION_2026_09_24_001", operator_id=op1.id, device_id=dev.id, environment="kitchen")
    s2 = rg.session(db, "SESSION_2026_09_24_002", operator_id=op2.id, environment="workshop")
    v1, v2 = rg.video(db, "a.mp4", session_id=s1.id), rg.video(db, "b.mp4", session_id=s2.id)
    _, e1 = rg.movement_run(db, v1, [rg.Ev("grasp", 10, 40, 0.9, obj="cup"), rg.Ev("release", 50, 60, 0.8, obj="cup"),
                                     rg.Ev("point", 100, 130, 0.7), rg.Ev("tap", 150, 152, 0.4, obj="cup")])  # fmt: skip
    _, e2 = rg.movement_run(db, v2, [rg.Ev("grasp", 5, 30, 0.95, obj="drill", hand="left"),
                                     rg.Ev("hold", 31, 90, 0.85, obj="drill", hand="left")])  # fmt: skip
    return {
        "sessions": (s1, s2),
        "videos": (v1, v2),
        "events": e1 + e2,
        "device": dev,
        "operators": (op1, op2),
    }


# --- acceptance ----------------------------------------------------------------------------------------


def test_rebuilding_a_version_from_its_spec_gives_an_identical_hash(client, db, h, enqueued):
    w = _world(db)
    ev = w["events"]
    for e in ev[:3]:
        client.post(f"/api/v1/review/events/{e.id}/status", json={"status": "confirmed"}, headers=h)
    client.post(f"/api/v1/review/events/{ev[4].id}/correct", json={"class": "pick_up"}, headers=h)
    ds = _dataset(client, h)
    v1 = _build(client, h, enqueued, ds, filters={"statuses": ["confirmed", "auto_detected"]})
    got = _samples(client, h, v1["id"])
    assert (
        v1["sample_count"] == len(got) == 5
    )  # tap is needs_review (0.4); the grasp is replaced by its correction
    assert {s["class_name"] for s in got} == {"grasp", "release", "point", "pick_up", "hold"}
    assert v1["content_hash"] and len(v1["content_hash"]) == 64

    # The data changes afterwards: more reviews, a correction of a sample, a new model run on a video.
    client.post(f"/api/v1/review/events/{ev[5].id}/status", json={"status": "rejected"}, headers=h)
    client.post(f"/api/v1/review/events/{ev[0].id}/correct", json={"class": "pinch"}, headers=h)
    client.post(f"/api/v1/review/events/{ev[3].id}/status", json={"status": "confirmed"}, headers=h)
    rg.movement_run(
        db, w["videos"][0], [rg.Ev("grasp", 12, 41, 0.5)], mv=rg.model_version(db, config={"x": 1})
    )

    check = _check(client, h, enqueued, v1["id"])
    assert check["status"] == "ready" and check["matches"] is True
    assert check["content_hash"] == v1["content_hash"] and check["sample_count"] == 5
    # The version itself is unchanged, while the same spec built now gives something else.
    assert [s["id"] for s in _samples(client, h, v1["id"])] == [s["id"] for s in got]
    v2 = _build(client, h, enqueued, ds, filters={"statuses": ["confirmed", "auto_detected"]})
    assert v2["number"] == 2 and v2["parent_version_id"] == v1["id"]
    assert v2["content_hash"] != v1["content_hash"]


def test_lineage_reaches_the_raw_file_from_every_sample(client, db, h, enqueued):
    w = _world(db)
    client.post(f"/api/v1/review/events/{w['events'][0].id}/correct", json={"class": "pinch"}, headers=h)
    v = _build(
        client,
        h,
        enqueued,
        _dataset(client, h),
        filters={"statuses": ["confirmed", "auto_detected", "needs_review"]},
    )
    videos = {str(x.id): x for x in w["videos"]}
    samples = _samples(client, h, v["id"])
    assert len(samples) == 6
    for s in samples:
        g = client.get(f"{D}/samples/{s['id']}/lineage", headers=h).json()
        assert g["reaches_raw_file"] is True
        nodes = {n["id"]: n for n in g["nodes"]}
        raw = next(n for n in g["nodes"] if n["type"] == "raw_file")
        assert raw["detail"]["sha256"] == videos[s["video_id"]].sha256
        assert raw["detail"]["storage_key"] == videos[s["video_id"]].storage_key
        kinds = {n["type"] for n in g["nodes"]}
        assert {"sample", "dataset_version", "dataset", "annotation", "event", "cv_run", "model_version", "video",
                "frames", "session"} <= kinds  # fmt: skip
        runs = {n["detail"]["kind"] for n in g["nodes"] if n["type"] == "cv_run"}
        assert runs == {"movement", "hand_tracking"}
        assert (
            nodes[f"frames:{s['video_id']}:{s['start_frame']}-{s['end_frame']}"]["detail"]["start_frame"]
            == s["start_frame"]
        )
        if s["source"] == "auto_corrected":  # the correction leads back to the prediction it replaced
            rel = {(e["source"].split(":")[0], e["relation"], e["target"].split(":")[0]) for e in g["edges"]}
            assert ("annotation", "corrects", "annotation") in rel and ("event", "corrects", "event") in rel
    assert client.get(f"{D}/samples/{uuid.uuid4()}/lineage", headers=h).status_code == 404


# --- versions ------------------------------------------------------------------------------------------


def test_versions_are_immutable(client, db, h, enqueued):
    _world(db)
    v = _build(client, h, enqueued, _dataset(client, h), filters={"statuses": ["auto_detected"]})
    vid = uuid.UUID(v["id"])
    with pytest.raises(DBAPIError, match="immutable"):
        db.execute(update(DatasetVersion).where(DatasetVersion.id == vid).values(content_hash="0" * 64))
        db.flush()
    db.rollback()
    with pytest.raises(DBAPIError, match="immutable"):
        db.execute(
            update(DatasetVersionSample).where(DatasetVersionSample.version_id == vid).values(split="test")
        )
        db.flush()
    db.rollback()
    with pytest.raises(DBAPIError, match="immutable"):
        db.execute(text("DELETE FROM dataset_version_samples WHERE version_id = :v"), {"v": vid})
    db.rollback()
    assert db.scalar(select(DatasetVersion.content_hash).where(DatasetVersion.id == vid)) == v["content_hash"]


def test_spec_filters(client, db, h, enqueued):
    w = _world(db)
    s1, s2 = w["sessions"]
    ds = _dataset(client, h)
    any_status = ["auto_detected", "needs_review", "confirmed"]

    def classes(**filters) -> list[str]:
        res = client.post(
            f"{D}/preview", json={"filters": {"statuses": any_status, **filters}}, headers=h
        ).json()
        return sorted(s["class_name"] for s in res["sample"])

    assert classes() == ["grasp", "grasp", "hold", "point", "release", "tap"]
    assert classes(session_ids=[str(s2.id)]) == ["grasp", "hold"]
    assert classes(device_ids=[str(w["device"].id)]) == ["grasp", "point", "release", "tap"]
    assert classes(environments=["workshop"]) == ["grasp", "hold"]
    assert classes(classes=["grasp"]) == ["grasp", "grasp"]
    assert classes(min_confidence=0.85) == ["grasp", "grasp", "hold"]
    assert classes(max_confidence=0.75) == ["point", "tap"]
    assert classes(handedness=["left"]) == ["grasp", "hold"]
    assert classes(object_labels=["cup"]) == ["grasp", "release", "tap"]
    assert classes(require_object=False) == ["point"]
    assert classes(statuses=["needs_review"]) == ["tap"]
    # Confirmed by a person, not by an auto-accept rule.
    client.post("/api/v1/review/rules", json={"min_confidence": 0.8}, headers=h)
    client.post("/api/v1/review/rules/apply", json={}, headers=h)
    client.post(f"/api/v1/review/events/{w['events'][2].id}/status", json={"status": "confirmed"}, headers=h)
    assert classes(statuses=["confirmed"]) == ["grasp", "grasp", "hold", "point", "release"]
    assert classes(statuses=["confirmed"], human_verified_only=True) == ["point"]
    # Quality flags leave whole videos out.
    db.execute(update(type(w["videos"][0])).where(type(w["videos"][0]).id == w["videos"][1].id)
               .values(quality_flags=["hand_tracking_failures"]))  # fmt: skip
    db.commit()
    assert classes(exclude_quality_flags=["hand_tracking_failures"]) == ["grasp", "point", "release", "tap"]
    facets = client.get(f"{D}/facets", headers=h).json()
    assert {f["flag"]: f["videos"] for f in facets["quality_flags"]}["hand_tracking_failures"] == 1
    assert facets["environments"] == ["kitchen", "workshop"] and "cup" in facets["object_labels"]
    # No classified video matches: nothing to build.
    res = client.post(
        f"{D}/{ds}/versions", json={"spec": {"filters": {"environments": ["garden"]}}}, headers=h
    )
    assert res.status_code == 422


def test_splits_keep_each_group_together(client, db, h, enqueued):
    ops = [Operator(name=f"Op {i}") for i in range(4)]
    db.add_all(ops)
    db.commit()
    for i in range(12):
        s = rg.session(db, f"SESSION_2026_09_24_{i + 1:03d}", operator_id=ops[i % 4].id)
        v = rg.video(db, f"v{i}.mp4", session_id=s.id)
        rg.movement_run(db, v, [rg.Ev("grasp", 10 * k, 10 * k + 5, 0.9) for k in range(5)])
    ds = _dataset(client, h)
    for group_by, groups in (("session", 12), ("operator", 4), ("video", 12), ("sample", 60)):
        v = _build(client, h, enqueued, ds, filters={"statuses": ["auto_detected"]},
                   split={"train": 0.5, "val": 0.25, "test": 0.25, "group_by": group_by, "seed": 7})  # fmt: skip
        samples = _samples(client, h, v["id"])
        by_group: dict[str, set[str]] = {}
        for s in samples:
            by_group.setdefault(s["group_key"], set()).add(s["split"])
        assert len(by_group) == groups
        assert all(len(splits) == 1 for splits in by_group.values()), group_by  # never across splits
        assert sum(v["counts"]["splits"].values()) == 60
        assert sum(v["counts"]["groups"].values()) == groups
        prefix = {"session": "session:", "operator": "operator:", "video": "video:", "sample": "sample:"}[
            group_by
        ]
        assert all(k.startswith(prefix) for k in by_group)
    # The same seed gives the same assignment; another seed another one.
    spec = {"filters": {"statuses": ["auto_detected"]}, "split": {"group_by": "sample", "seed": 1}}
    a = client.post(f"{D}/preview", json=spec, headers=h).json()["counts"]["splits"]
    b = client.post(f"{D}/preview", json=spec, headers=h).json()["counts"]["splits"]
    assert a == b
    bad = client.post(f"{D}/preview", json={"split": {"train": 0.9, "val": 0.2, "test": 0}}, headers=h)
    assert bad.status_code == 422


def test_versions_read_the_data_as_of_their_build(client, db, h, enqueued):
    s = rg.session(db)
    v = rg.video(db, session_id=s.id)
    _, (a, b) = rg.movement_run(db, v, [rg.Ev("grasp", 10, 40, 0.9), rg.Ev("hold", 41, 90, 0.9)])
    fix = client.post(
        f"/api/v1/review/events/{a.id}/correct", json={"class": "pinch", "end_frame": 35}, headers=h
    ).json()
    ds = _dataset(client, h)
    v1 = _build(client, h, enqueued, ds, filters={"statuses": ["confirmed"]})
    (only,) = _samples(client, h, v1["id"])
    assert (only["class_name"], only["end_frame"], only["annotation_revision"]) == ("pinch", 35, 1)
    # Later: the correction is edited again, and the other event is confirmed.
    client.patch(f"/api/v1/annotations/{fix['event']['annotation_id']}", json={"frame_end": 30}, headers=h)
    client.post(f"/api/v1/review/events/{b.id}/status", json={"status": "confirmed"}, headers=h)
    check = _check(client, h, enqueued, v1["id"])
    assert check["matches"] is True
    v2 = _build(client, h, enqueued, ds, filters={"statuses": ["confirmed"]})
    now = {x["class_name"]: x for x in _samples(client, h, v2["id"])}
    assert (
        set(now) == {"pinch", "hold"}
        and now["pinch"]["end_frame"] == 30
        and now["pinch"]["annotation_revision"] == 2
    )


def test_preview_matches_the_built_version(client, db, h, enqueued):
    _world(db)
    spec = {
        "filters": {"statuses": ["auto_detected", "needs_review"]},
        "split": {"group_by": "video", "seed": 3},
    }
    p = client.post(f"{D}/preview", json=spec, headers=h).json()
    v = _build(client, h, enqueued, _dataset(client, h), **spec)
    assert p["sample_count"] == v["sample_count"] == 6 and p["counts"] == v["counts"] and not p["truncated"]
    assert p["videos"] == 2 and p["runs"] == 2
    detail = client.get(f"{D}/versions/{v['id']}", headers=h).json()
    assert detail["spec"]["split"]["group_by"] == "video"
    assert (
        len(detail["inputs"]["videos"]) == 2
        and len(detail["inputs"]["runs"]) == 2
        and detail["inputs"]["as_of"]
    )
    assert {m["name"] for m in detail["model_versions"]} == {"test-movement", "test-hand_tracking"}
    listed = client.get(D, headers=h).json()["items"][0]
    assert (listed["version_count"], listed["latest_version"]) == (1, 1)


def test_only_writers_build_and_failed_builds_say_why(client, db, h, enqueued, viewer):
    _world(db)
    ds = _dataset(client, h)
    vh = auth_header(viewer)
    assert client.post(f"{D}/{ds}/versions", json={}, headers=vh).status_code == 403
    assert client.post(f"{D}/preview", json={}, headers=vh).status_code == 200  # reading is fine
    res = client.post(
        f"{D}/{ds}/versions", json={"spec": {"filters": {"statuses": ["auto_detected"]}}}, headers=h
    )
    vid = res.json()["id"]
    # Break the pinned inputs before the worker runs: the build fails with the reason, and stays failed.
    db.execute(text("UPDATE dataset_versions SET inputs = jsonb_set(inputs, '{as_of}', '\"not a time\"') WHERE id = :v"),
               {"v": vid})  # fmt: skip
    db.commit()
    drain(enqueued)
    v = client.get(f"{D}/versions/{vid}", headers=h).json()
    assert v["status"] == "failed" and v["error"]
    assert client.post(f"{D}/versions/{vid}/exports", json={"format": "jsonl"}, headers=h).status_code == 409
    assert db.get(Dataset, uuid.UUID(ds)) is not None
