"""
Movement classification end to end (spec Phase 4 acceptance): real hand and object models on clips with
known motion, through upload, the chained worker jobs, Parquet, and the API.

- "Events appear on the Phase 2 timeline automatically": one request runs hand tracking and object
  detection, then movement classification on their output, and the movement and object-interaction tracks
  fill without another step.
- "Each event links back to the exact keypoint frames that produced it": every evidence frame is a keypoint
  row of the hand-tracking run, and each stored measurement recomputes from those rows.

The clips come from `egolabs.cv.samples`: MediaPipe's test photos moved on scripted paths, so which movement
happens in which frames is known.
"""

import io
import json
import uuid
from itertools import accumulate

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from sqlalchemy import select

from egolabs import storage
from egolabs.config import get_settings
from egolabs.cv import samples
from egolabs.models import Annotation, CvRun, LineageEdge, MovementEvent, Upload
from tests.conftest import auth_header, drain, user_with_role
from tests.media import upload_file

W, H = 640, 480


@pytest.fixture
def h(admin):
    return auth_header(admin)


def _video(client, db, h, enqueued, path) -> str:
    upload = upload_file(client, h, path)
    drain(enqueued)
    return str(db.get(Upload, uuid.UUID(upload["id"])).video_id)


def _analyse(client, h, enqueued, video_id: str, **body) -> dict[str, dict]:
    res = client.post("/api/v1/cv/runs", json={"video_ids": [video_id], **body}, headers=h)
    assert res.status_code == 201, res.text
    created = {r["kind"]: r for r in res.json()}
    drain(enqueued)
    runs = {k: client.get(f"/api/v1/cv/runs/{r['id']}", headers=h).json() for k, r in created.items()}
    for kind, run in runs.items():
        assert run["status"] == "succeeded", (kind, run["error"])
    return runs


def _events(client, h, video_id: str, **params) -> list[dict]:
    res = client.get(
        "/api/v1/movement/events", params={"video_id": video_id, "limit": 500, **params}, headers=h
    )
    assert res.status_code == 200, res.text
    return res.json()["items"]


def _windows(lengths: list[int]) -> list[tuple[int, int]]:
    """[start, end] frames of consecutive clip segments."""
    ends = list(accumulate(lengths))
    return [(e - n, e - 1) for n, e in zip(lengths, ends, strict=True)]


def _within(event: dict, window: tuple[int, int], slack: int = 8) -> bool:
    return window[0] - slack <= event["start_frame"] and event["end_frame"] <= window[1] + slack


def _parquet_rows(run_row: CvRun, kind: str) -> list[dict]:
    tables = [
        pq.read_table(io.BytesIO(storage.get_bytes(get_settings().s3_bucket_derived, k)))
        for k in run_row.output[kind]
    ]
    return pa.concat_tables(tables).to_pylist()


def _evidence(client, h, event_id: str) -> list[dict]:
    frames, offset = [], 0
    while True:
        page = client.get(f"/api/v1/movement/events/{event_id}/evidence", params={"offset": offset, "limit": 100},
                          headers=h).json()  # fmt: skip
        frames += page["frames"]
        offset += page["limit"]
        if offset >= page["total"]:
            return frames


@pytest.fixture(scope="module")
def grasp(tmp_path_factory):
    return samples.make_scene_clip(tmp_path_factory.mktemp("mv") / "grasp.mp4", samples.grasp_scene())


@pytest.fixture(scope="module")
def press(tmp_path_factory):
    return samples.make_scene_clip(tmp_path_factory.mktemp("mv") / "press.mp4", samples.press_and_tap_scene())


@pytest.fixture(scope="module")
def gestures(tmp_path_factory):
    return samples.make_clip(tmp_path_factory.mktemp("mv") / "gestures.mp4", samples.GESTURE_SEGMENTS)


def test_one_request_puts_events_on_the_timeline(client, db, h, enqueued, grasp):
    video_id = _video(client, db, h, enqueued, grasp.path)
    res = client.post("/api/v1/cv/runs", json={"video_ids": [video_id]}, headers=h)
    created = {r["kind"]: r for r in res.json()}
    assert list(created) == ["hand_tracking", "object_detection", "movement"]
    assert created["movement"]["status"] == "waiting" and created["movement"]["job_id"] is None
    assert created["movement"]["inputs"] == {"hand_tracking": created["hand_tracking"]["id"],
                                             "object_detection": created["object_detection"]["id"]}  # fmt: skip
    drain(enqueued)  # the worker: hand tracking and object detection, then movement once both succeed
    runs = {k: client.get(f"/api/v1/cv/runs/{r['id']}", headers=h).json() for k, r in created.items()}
    assert {k: r["status"] for k, r in runs.items()} == dict.fromkeys(runs, "succeeded")
    assert runs["movement"]["model_version"]["name"] == "rules"
    assert runs["object_detection"]["model_version"]["name"] == "mediapipe-objects"

    # The object detector finds the burger ("sandwich" in COCO) through the clip.
    burger = max(runs["object_detection"]["object_tracks"], key=lambda t: t["frames_detected"])
    assert burger["label"] == "sandwich" and burger["frames_detected"] >= 0.9 * len(grasp.frames)

    # The scripted motion, segment by segment, becomes these events in this order.
    w = _windows([s.frames for s in samples.grasp_scene()])
    events = _events(client, h, video_id)
    assert [e["movement_class"]["name"] for e in events] == [
        "hand_enter", "reach", "grasp", "hold", "pick_up", "move", "put_down", "release", "hand_exit",
    ], [(e["label"], e["start_frame"], e["end_frame"]) for e in events]  # fmt: skip
    by = {e["movement_class"]["name"]: e for e in events}
    assert _within(by["reach"], w[1]) and _within(by["hold"], w[2]) and _within(by["pick_up"], w[3])
    assert _within(by["move"], w[5]) and _within(by["put_down"], w[6]) and _within(by["release"], w[7])
    assert by["move"]["label"] == "Move · left" and by["move"]["attributes"]["direction"] == "left"
    for name in ("reach", "grasp", "hold", "pick_up", "move", "put_down", "release"):
        assert by[name]["object_label"] == "sandwich" and by[name]["object_track_id"] == burger["track_id"]
    assert all(e["handedness"] == "right" and 0 < e["confidence"] <= 1 for e in events)
    assert all(e["model_version"]["id"] == runs["movement"]["model_version"]["id"] for e in events)

    # …and on the Phase 2 timeline, with no further step: the movement track holds exactly these events,
    # the object track the hand–burger contact.
    tl = client.get(f"/api/v1/videos/{video_id}/timeline", headers=h).json()
    tracks = {t["id"]: t for t in tl["tracks"]}
    assert tracks["movement"]["filled_from_phase"] is None and tracks["object"]["filled_from_phase"] is None
    assert sorted(s["id"] for s in tracks["movement"]["segments"]) == sorted(
        e["annotation_id"] for e in events
    )
    seg = {s["id"]: s for s in tracks["movement"]["segments"]}
    assert all((seg[e["annotation_id"]]["start"], seg[e["annotation_id"]]["end"]) == (e["start_frame"], e["end_frame"])
               for e in events)  # fmt: skip
    (contact,) = tracks["object"]["segments"]
    assert contact["label"] == "right hand · sandwich"
    assert contact["start"] <= by["grasp"]["start_frame"] and contact["end"] >= by["release"]["end_frame"]
    # Shift+→ in the inspector steps through them.
    nxt = client.get(f"/api/v1/videos/{video_id}/annotations/adjacent", params={"frame": by["hold"]["start_frame"]},
                     headers=h).json()  # fmt: skip
    assert nxt["frame"] == by["pick_up"]["start_frame"]

    # Lineage: the movement run was made from the hand and object runs by the classifier's model version.
    edges = {(e.parent_type, e.parent_id, e.relation)
             for e in db.scalars(select(LineageEdge).where(LineageEdge.child_id == uuid.UUID(runs["movement"]["id"])))}  # fmt: skip
    assert edges == {("cv_run", uuid.UUID(runs["hand_tracking"]["id"]), "input_of"),
                     ("cv_run", uuid.UUID(runs["object_detection"]["id"]), "input_of"),
                     ("model_version", uuid.UUID(runs["movement"]["model_version"]["id"]), "model_of")}  # fmt: skip

    # The interaction graph: Hand → Finger(s) → Movement → Object → Time range.
    graph = client.get("/api/v1/movement/graph", params={"video_id": video_id}, headers=h).json()
    assert graph["total_events"] == len(events)
    nodes = {n["id"]: n for n in graph["nodes"]}
    assert nodes["hand:right"]["count"] == len(events) and nodes["object:sandwich"]["count"] == 7
    links = {(link["source"], link["target"]): link["count"] for link in graph["links"]}
    assert (
        links[("movement:pick_up", "object:sandwich")] == 1
        and links[("hand:right", "finger:whole_hand")] == 3  # enter, reach, exit
    )
    path = next(e for e in graph["events"] if e["id"] == by["pick_up"]["id"])
    assert path["path"][0] == "hand:right" and path["path"][-2:] == ["movement:pick_up", "object:sandwich"]
    assert (path["start_frame"], path["end_frame"]) == (
        by["pick_up"]["start_frame"],
        by["pick_up"]["end_frame"],
    )


def test_every_event_traces_to_its_exact_keypoint_frames(client, db, h, enqueued, grasp):
    video_id = _video(client, db, h, enqueued, grasp.path)
    runs = _analyse(client, h, enqueued, video_id)
    hand_run = db.get(CvRun, uuid.UUID(runs["hand_tracking"]["id"]))
    rows = {(r["frame"], r["track_id"]): r for r in _parquet_rows(hand_run, "hands")}
    events = _events(client, h, video_id)
    assert events
    for e in events:
        detail = client.get(f"/api/v1/movement/events/{e['id']}", headers=h).json()
        ev = detail["evidence"]
        assert ev["hand_run_id"] == runs["hand_tracking"]["id"] and ev["track_id"] == e["hand_track_id"]
        assert ev["frames"] == sorted(ev["frames"]) and len(ev["frames"]) == ev["frame_count"] > 0
        assert (ev["frames"][0], ev["frames"][-1]) == (e["start_frame"], e["end_frame"])
        assert ev["rule"] and all(len(v) == ev["frame_count"] for v in ev["measurements"].values())
        assert set(ev["parts"]) <= set(hand_run.output["hands"])
        # Every evidence frame is a keypoint row of that hand track in the hand-tracking run's Parquet…
        frames = _evidence(client, h, e["id"])
        assert [f["frame"] for f in frames] == ev["frames"]
        for f in frames:
            row = rows[(f["frame"], e["hand_track_id"])]
            assert row["model_version_id"] == runs["hand_tracking"]["model_version"]["id"]
            assert np.allclose(np.array(f["keypoints"]), np.stack([row["kp_x"], row["kp_y"]], axis=1))
            px = np.stack([row["kp_x"], row["kp_y"]], axis=1) * [W, H]
            # …and the measurements the rule compared recompute from those keypoints.
            if "wrist_x_px" in f["values"]:
                assert f["values"]["wrist_x_px"] == pytest.approx(px[0, 0], abs=0.01)
            if "object_center_y_px" in f["values"]:
                b = f["object_bbox"]
                assert f["values"]["object_center_y_px"] == pytest.approx((b[1] + b[3] / 2) * H, abs=0.01)
            if "distance_to_object_px" in f["values"]:
                b = frames[-1]["object_bbox"]  # reach: distance to the box where contact began
                x0, y0, x1, y1 = b[0] * W, b[1] * H, (b[0] + b[2]) * W, (b[1] + b[3]) * H
                d = min(
                    float(np.hypot(max(x0 - x, 0, x - x1), max(y0 - y, 0, y - y1)))
                    for x, y in px[[4, 8, 12, 16, 20]]
                )
                assert f["values"]["distance_to_object_px"] == pytest.approx(d, abs=0.02)
        # The event row, its timeline segment, and its evidence agree.
        row = db.get(MovementEvent, uuid.UUID(e["id"]))
        ann = db.get(Annotation, row.annotation_id)
        assert (ann.frame_start, ann.frame_end, ann.category.value, ann.source.value) == (
            e["start_frame"], e["end_frame"], "movement", "auto")  # fmt: skip
        assert ann.confidence == e["confidence"] and ann.model_version_id == row.model_version_id
        assert ann.data["event_id"] == e["id"]


def test_pointing_press_tap_on_real_hands(client, db, h, enqueued, press):
    video_id = _video(client, db, h, enqueued, press.path)
    runs = _analyse(client, h, enqueued, video_id)
    w = _windows([s.frames for s in samples.press_and_tap_scene()])
    events = _events(client, h, video_id)
    names = [e["movement_class"]["name"] for e in events]
    assert names == ["hand_enter", "reach", "press", "point", "reach", "tap", "point", "hand_exit"], names
    by = {}
    for e in events:
        by.setdefault(e["movement_class"]["name"], []).append(e)
    assert _within(by["press"][0], w[2]) and _within(by["tap"][0], (w[5][0], w[7][1]))
    assert _within(by["point"][0], w[4]) and _within(by["point"][1], w[8])
    assert by["hand_exit"][0]["attributes"]["edge"] == "right"
    assert "index" in by["press"][0]["fingers"] and by["point"][0]["fingers"] == ["index"]
    # The hand tracker lost the hand in the fast tap and found it again under a new ID: that's no exit
    # and re-entrance, and the Phase 3 run records it as a tracking failure or new track.
    assert (
        len(runs["hand_tracking"]["hand_tracks"]) >= 2 and len(by["hand_enter"]) == len(by["hand_exit"]) == 1
    )
    # Point: index straightness recomputes from the Parquet keypoints (3-D, as the rule measures it).
    hand_run = db.get(CvRun, uuid.UUID(runs["hand_tracking"]["id"]))
    rows = {(r["frame"], r["track_id"]): r for r in _parquet_rows(hand_run, "hands")}
    point = by["point"][0]
    for f in _evidence(client, h, point["id"]):
        r = rows[(f["frame"], point["hand_track_id"])]
        p = np.stack([r["kp_x"], r["kp_y"], r["kp_z"]], axis=1) * [W, H, W]
        path = sum(np.linalg.norm(p[i + 1] - p[i]) for i in (5, 6, 7))
        assert f["values"]["index_straightness"] == pytest.approx(
            np.linalg.norm(p[8] - p[5]) / path, abs=1e-3
        )


def test_pinch_swipe_rotate_on_real_hands(client, db, h, enqueued, gestures):
    video_id = _video(client, db, h, enqueued, gestures.path)
    runs = _analyse(client, h, enqueued, video_id)
    assert runs["movement"]["inputs"].keys() == {"hand_tracking", "object_detection"}
    w = _windows([s if isinstance(s, int) else s.frames for s in samples.GESTURE_SEGMENTS])
    events = _events(client, h, video_id)
    by = {}
    for e in events:
        by.setdefault(e["movement_class"]["name"], []).append(e)
    assert set(by) == {"pinch", "point", "swipe", "rotate", "hand_enter", "hand_exit"}, set(by)
    (pinch,) = by["pinch"]
    (swipe,) = by["swipe"]
    (rotate,) = by["rotate"]
    assert _within(pinch, w[0]) and pinch["fingers"] == ["thumb", "index"]
    assert _within(swipe, w[3]) and swipe["attributes"]["direction"] == "right"
    assert _within(rotate, w[7]) and rotate["attributes"]["direction"] == "clockwise"
    assert 75 <= rotate["attributes"]["degrees"] <= 105  # the photo turns 90°
    assert not any(e["object_label"] for e in events)  # a one-frame false detection makes no contact
    # Pinch: thumb–index distance per hand size recomputes from the evidence keypoints.
    for f in _evidence(client, h, pinch["id"]):
        p = np.array(f["keypoints"]) * [W, H]
        want = np.linalg.norm(p[4] - p[8]) / np.linalg.norm(p[0] - p[9])
        assert f["values"]["thumb_index_distance"] == pytest.approx(want, abs=1e-3) and want < 0.3


def test_reclassify_with_a_class_switched_off(client, db, h, enqueued, press, admin):
    video_id = _video(client, db, h, enqueued, press.path)
    first = _analyse(client, h, enqueued, video_id)
    classes = {c["name"]: c for c in client.get("/api/v1/movement/classes", headers=h).json()}
    assert classes["point"]["events"] == 2 and classes["point"]["active"]
    assert client.patch(f"/api/v1/movement/classes/{classes['point']['id']}", json={"active": False},
                        headers=h).status_code == 200  # fmt: skip

    # Movement alone: it re-reads the latest hand and object runs; nothing is tracked again.
    second = _analyse(client, h, enqueued, video_id, kinds=["movement"])
    assert list(second) == ["movement"]
    assert second["movement"]["inputs"] == {"hand_tracking": first["hand_tracking"]["id"],
                                            "object_detection": first["object_detection"]["id"]}  # fmt: skip
    assert second["movement"]["stats"]["skipped_inactive"] == {"point": 2}
    events = _events(client, h, video_id)
    assert {e["run_id"] for e in events} == {second["movement"]["id"]}
    assert "point" not in {e["movement_class"]["name"] for e in events}
    tl = {t["id"]: t for t in client.get(f"/api/v1/videos/{video_id}/timeline", headers=h).json()["tracks"]}
    assert len(tl["movement"]["segments"]) == len(events)  # the newest run's events only
    old = _events(client, h, video_id, run_id=first["movement"]["id"])
    assert len(old) == len(events) + 2  # the first run's events are kept


def test_swapping_the_classifier_is_configuration_only(client, db, h, enqueued, press, monkeypatch):
    video_id = _video(client, db, h, enqueued, press.path)
    first = _analyse(client, h, enqueued, video_id, kinds=["hand_tracking", "movement"])
    assert "object_detection" not in first["movement"]["inputs"]
    track = first["hand_tracking"]["hand_tracks"][0]["track_id"]
    # A "learned model" run elsewhere: its output as JSON Lines, including a class nobody defined yet, and a
    # frame the hand track has no keypoints for (dropped: an event must trace to keypoint frames).
    lines = [{"class": "wave", "track_id": track, "frames": [20, 21, 22, 5000], "confidence": 0.9},
             {"class": "grasp", "track_id": track, "frames": [70, 71], "confidence": 0.4}]  # fmt: skip
    sha = client.get(f"/api/v1/videos/{video_id}", headers=h).json()["sha256"]
    storage.put_bytes("\n".join(json.dumps(line) for line in lines).encode(), get_settings().s3_bucket_derived,
                      f"events/{sha}.jsonl")  # fmt: skip
    monkeypatch.setenv("MOVEMENT_CLASSIFIER_ADAPTER", "events-file")
    monkeypatch.setenv("MOVEMENT_CLASSIFIER_CONFIG", json.dumps({
        "source": f"s3://{get_settings().s3_bucket_derived}/events/{{sha256}}.jsonl", "name": "wave-net", "version": "3",
    }))  # fmt: skip
    get_settings.cache_clear()
    try:
        info = client.get("/api/v1/cv/adapters", params={"kind": "movement"}, headers=h).json()
        assert (info["name"], info["runnable"], info["env"]) == (
            "events-file", True, ["MOVEMENT_CLASSIFIER_ADAPTER", "MOVEMENT_CLASSIFIER_CONFIG"])  # fmt: skip
        second = _analyse(client, h, enqueued, video_id, kinds=["movement"])
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
    assert second["movement"]["model_version"]["name"] == "wave-net"
    assert second["movement"]["stats"]["dropped_frames"] == 1
    events = _events(client, h, video_id)
    assert [(e["movement_class"]["name"], e["start_frame"], e["end_frame"], e["status"]) for e in events] == [
        ("wave", 20, 22, "auto_detected"), ("grasp", 70, 71, "needs_review")]  # fmt: skip
    wave = next(c for c in client.get("/api/v1/movement/classes", headers=h).json() if c["name"] == "wave")
    assert not wave["builtin"] and "wave-net" in wave["description"]


def test_a_failed_input_fails_the_waiting_run(client, db, h, enqueued, press, monkeypatch):
    video_id = _video(client, db, h, enqueued, press.path)
    monkeypatch.setenv("HAND_TRACKING_ADAPTER", "rtmpose-hands")  # a documented stub: fails to load
    get_settings.cache_clear()
    try:
        res = client.post("/api/v1/cv/runs", json={"video_ids": [video_id], "kinds": ["hand_tracking", "movement"]},
                          headers=h).json()  # fmt: skip
        drain(enqueued)
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
    runs = {r["kind"]: client.get(f"/api/v1/cv/runs/{r['id']}", headers=h).json() for r in res}
    assert runs["hand_tracking"]["status"] == "failed"
    assert runs["movement"]["status"] == "failed" and "did not succeed" in runs["movement"]["error"]
    assert runs["movement"]["job_id"] is None  # never queued
    # Movement alone needs a successful hand-tracking run to read.
    res = client.post("/api/v1/cv/runs", json={"video_ids": [video_id], "kinds": ["movement"]}, headers=h)
    assert res.status_code == 409 and "hand-tracking" in res.json()["detail"]


def test_reviewing_events(client, db, h, enqueued, press, viewer):
    video_id = _video(client, db, h, enqueued, press.path)
    _analyse(client, h, enqueued, video_id)
    events = {e["movement_class"]["name"]: e for e in _events(client, h, video_id)}
    press_ev, tap = events["press"], events["tap"]
    url = f"/api/v1/movement/events/{press_ev['id']}"
    assert client.patch(url, json={"status": "confirmed"}, headers=auth_header(viewer)).status_code == 403

    confirmed = client.patch(url, json={"status": "confirmed"}, headers=h).json()
    assert confirmed["status"] == "confirmed" and confirmed["reviewed_by"]["name"]
    rejected = client.patch(url, json={"status": "rejected"}, headers=h).json()
    assert rejected["status"] == "rejected" and rejected["annotation"]["deleted_at"]
    # Rejected: off the timeline, still in the database and its history.
    tl = {t["id"]: t for t in client.get(f"/api/v1/videos/{video_id}/timeline", headers=h).json()["tracks"]}
    assert press_ev["annotation_id"] not in {s["id"] for s in tl["movement"]["segments"]}
    history = client.get(f"/api/v1/annotations/{press_ev['annotation_id']}/history", headers=h).json()
    assert history["revisions"][-1]["action"] == "deleted"
    assert "rejected" not in {e["status"] for e in _events(client, h, video_id, status="auto_detected")}
    restored = client.patch(url, json={"status": "needs_review"}, headers=h).json()
    assert restored["annotation"]["deleted_at"] is None and restored["annotation"]["needs_review"] is True

    # Correcting the event's segment in the inspector keeps the prediction and marks the event corrected.
    fixed = client.patch(f"/api/v1/annotations/{tap['annotation_id']}", json={"frame_end": tap["end_frame"] + 2},
                         headers=h).json()  # fmt: skip
    assert fixed["source"] == "auto_corrected" and fixed["parent_annotation_id"] == tap["annotation_id"]
    after = client.get(f"/api/v1/movement/events/{tap['id']}", headers=h).json()
    assert after["status"] == "corrected" and after["annotation"]["superseded_at"]
    assert (
        client.patch(
            f"/api/v1/movement/events/{tap['id']}", json={"status": "confirmed"}, headers=h
        ).status_code
        == 409
    )
    # Flagging a segment in the inspector (R) puts its event up for review.
    point = events["point"]
    client.patch(f"/api/v1/annotations/{point['annotation_id']}", json={"needs_review": True}, headers=h)
    assert client.get(f"/api/v1/movement/events/{point['id']}", headers=h).json()["status"] == "needs_review"


def test_objects_api_matches_the_scripted_box(client, db, h, enqueued, grasp):
    video_id = _video(client, db, h, enqueued, grasp.path)
    runs = _analyse(client, h, enqueued, video_id, kinds=["object_detection"])
    run = runs["object_detection"]
    assert run["tracks"] >= 1 and run["stats"]["labels"]["sandwich"]["mean_score"] > 0.5
    boxes = client.get(f"/api/v1/cv/runs/{run['id']}/objects", params={"frame_from": 0, "frame_to": 14},
                       headers=h).json()  # fmt: skip
    assert [f["frame"] for f in boxes["frames"]] == list(range(15)) and boxes["model_version_id"] == run[
        "model_version"
    ]["id"]
    for f in boxes["frames"]:  # no hand in these frames: the detector's box is the burger photo's box
        (o,) = [x for x in f["objects"] if x["label"] == "sandwich"]
        bx, by_, bw, bh = o["bbox"]
        x0, y0, x1, y1 = grasp.frames[f["frame"]].object_box
        inter = max(0, min(bx + bw, x1 / W) - max(bx, x0 / W)) * max(
            0, min(by_ + bh, y1 / H) - max(by_, y0 / H)
        )
        union = bw * bh + (x1 - x0) * (y1 - y0) / (W * H) - inter
        assert inter / union > 0.7
    assert client.get(f"/api/v1/cv/runs/{run['id']}/frames", headers=h).status_code == 422  # not a hand run
    info = client.get("/api/v1/cv/adapters", params={"kind": "object_detection"}, headers=h).json()
    assert (
        info["name"] == "mediapipe-objects"
        and "sandwich" in info["detects"]
        and info["stubs"] == ["yolo-objects"]
    )
    assert info["model_version"]["id"] == run["model_version"]["id"]


def test_movement_classes_api(client, h, admin, viewer):
    annotator = user_with_role(client, admin, "ann@example.com", "annotator")
    reviewer = user_with_role(client, admin, "rev@example.com", "reviewer")
    classes = client.get("/api/v1/movement/classes", headers=auth_header(viewer)).json()
    assert [c["name"] for c in classes][:3] == ["hand_enter", "hand_exit", "reach"] and len(classes) == 20
    body = {
        "name": "screw_in",
        "label": "Screw in",
        "description": "Turning a screw into a hole.",
        "requires_object": True,
    }
    assert (
        client.post("/api/v1/movement/classes", json=body, headers=auth_header(annotator)).status_code == 403
    )
    made = client.post("/api/v1/movement/classes", json=body, headers=auth_header(reviewer))
    assert made.status_code == 201 and not made.json()["builtin"]
    assert client.post("/api/v1/movement/classes", json=body, headers=h).status_code == 409
    assert (
        client.post("/api/v1/movement/classes", json={**body, "name": "Bad Name"}, headers=h).status_code
        == 422
    )
    pinch = next(c for c in classes if c["name"] == "pinch")
    edited = client.patch(
        f"/api/v1/movement/classes/{pinch['id']}", json={"label": "Precision pinch"}, headers=h
    ).json()
    assert (edited["name"], edited["label"], edited["builtin"]) == ("pinch", "Precision pinch", True)
    assert client.get("/api/v1/movement/classes", headers=h).json()[-1]["name"] == "screw_in"
    assert client.get("/api/v1/movement/graph", headers=h).status_code == 422  # needs a video or session
    assert client.get(f"/api/v1/movement/events/{uuid.uuid4()}", headers=h).status_code == 404


def test_second_model_version_changes_the_review_queue(client, db, h, enqueued, grasp):
    """
    Phase 5 on real output: re-classifying with another rule configuration (a new model version) replaces
    the queue's items with the new run's, each compared with the first version's events.
    """
    video_id = _video(client, db, h, enqueued, grasp.path)
    _analyse(client, h, enqueued, video_id)
    before = client.get(
        "/api/v1/review/queue", params={"video_id": video_id, "limit": 200}, headers=h
    ).json()["items"]
    assert before and all(i["compared_versions"] == 0 and i["disagreement"] is None for i in before)
    res = client.post("/api/v1/review/auto-annotate",
                      json={"video_ids": [video_id], "kinds": ["movement"],
                            "models": {"movement": {"adapter": "rules", "config": {"hold_min_s": 2.5, "reach_distance": 0.2}}}},
                      headers=h)  # fmt: skip
    assert res.status_code == 201, res.text
    drain(enqueued)
    run = client.get(f"/api/v1/cv/runs/{res.json()['runs'][0]['id']}", headers=h).json()
    assert run["status"] == "succeeded", run["error"]
    first_mv = before[0]["model_version"]["id"]
    assert run["model_version"]["id"] != first_mv
    after = client.get("/api/v1/review/queue", params={"video_id": video_id, "limit": 200}, headers=h).json()[
        "items"
    ]
    assert after and {i["run_id"] for i in after} == {run["id"]}
    assert all(i["compared_versions"] == 1 and i["disagreement"] is not None for i in after)
    old = [(i["movement_class"]["name"], i["start_frame"], i["confidence"]) for i in before]
    new = [(i["movement_class"]["name"], i["start_frame"], i["confidence"]) for i in after]
    assert old != new  # longer hold_min_s drops the hold; the reach's margin (and confidence) shrinks
    assert ("hold", 55) in [o[:2] for o in old] and ("hold", 55) not in [n[:2] for n in new]
    assert [i["priority"] for i in after] == sorted((i["priority"] for i in after), reverse=True)
