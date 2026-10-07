"""
Hand tracking end to end (spec Phase 3 acceptance): real hands with known answers, through upload, the
worker, Parquet, and the API.

The clips are MediaPipe's hand test photos moved around the frame with a known transform per frame, so the
correct keypoint positions are the photos' published reference landmarks under that transform.
"""

import io
import json
import uuid

import numpy as np
import pyarrow.parquet as pq
import pytest
from sqlalchemy import select

from egolabs import storage
from egolabs.config import get_settings
from egolabs.cv import samples
from egolabs.models import (
    Annotation,
    CvRun,
    CvRunStatus,
    HandTrack,
    Job,
    JobStatus,
    LineageEdge,
    ModelVersion,
    Upload,
)
from tests.conftest import auth_header, drain
from tests.media import upload_file

SEGMENTS = [
    samples.Segment("pointing_up.jpg", 45, start=(0.3, 0.5), end=(0.4, 0.55)),
    12,  # no hands
    samples.Segment("victory.jpg", 45, start=(0.72, 0.5), end=(0.62, 0.45)),
    samples.Segment("thumb_up.jpg", 45, start=(0.3, 0.45), end=(0.45, 0.5), zoom=0.15),
]


@pytest.fixture
def h(admin):
    return auth_header(admin)


def _video(client, db, h, enqueued, clip: samples.SampleClip) -> str:
    upload = upload_file(client, h, clip.path)
    drain(enqueued)
    return str(db.get(Upload, uuid.UUID(upload["id"])).video_id)


def _run(client, h, enqueued, video_id: str, **body) -> dict:
    """Hand tracking alone (the Phase 4 steps that follow it by default are tested in test_movement_pipeline)."""
    body.setdefault("kinds", ["hand_tracking"])
    res = client.post("/api/v1/cv/runs", json={"video_ids": [video_id], **body}, headers=h)
    assert res.status_code == 201, res.text
    drain(enqueued)
    run = client.get(f"/api/v1/cv/runs/{res.json()[0]['id']}", headers=h).json()
    assert run["status"] == "succeeded", run["error"]
    return run


def _parquet(run_row: CvRun, kind: str):
    tables = [
        pq.read_table(io.BytesIO(storage.get_bytes(get_settings().s3_bucket_derived, k)))
        for k in run_row.output[kind]
    ]
    import pyarrow as pa

    return pa.concat_tables(tables).to_pydict()


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    return samples.make_clip(tmp_path_factory.mktemp("cv") / "hands.mp4", SEGMENTS)


def test_tracking_real_hands_matches_the_reference_landmarks(client, db, h, enqueued, clip):
    video_id = _video(client, db, h, enqueued, clip)
    run = _run(client, h, enqueued, video_id)
    n = len(clip.frames)
    assert (run["frames_total"], run["frames_processed"]) == (n, n)
    assert run["frames_with_hands"] == 135 and run["stats"]["frames_without_hands"] == 12
    assert run["stats"]["no_hand_ranges"] == [[45, 56]]
    assert run["tracks"] == 3 and run["tracking_failures"] == 0
    mv = run["model_version"]
    assert mv["name"] == "mediapipe-hands" and "hand_landmarker@fbc2a300" in mv["version"]

    row = db.get(CvRun, uuid.UUID(run["id"]))
    hands = _parquet(row, "hands")
    # Every output row references the model version (and its run and video).
    assert set(hands["model_version_id"]) == {mv["id"]}
    assert set(hands["run_id"]) == {run["id"]} and set(hands["video_id"]) == {video_id}
    fingers = _parquet(row, "fingers")
    assert set(fingers["model_version_id"]) == {mv["id"]} and len(fingers["frame"]) == 5 * len(hands["frame"])

    # Keypoints land where the reference landmarks say, frame by frame.
    refs = {p: samples.reference_landmarks(p) for p in ("pointing_up.jpg", "victory.jpg", "thumb_up.jpg")}
    sizes = {p: samples.photo_size(p) for p in refs}
    raw_err, smooth_err, tracks_by_photo = [], [], {}
    px = np.array([clip.width, clip.height])
    for i, frame in enumerate(hands["frame"]):
        photo, _ = clip.frames[frame]
        label, ref = refs[photo]
        expected = clip.expected(frame, ref, sizes[photo])
        raw = np.stack([hands["raw_kp_x"][i], hands["raw_kp_y"][i]], axis=1)
        smooth = np.stack([hands["kp_x"][i], hands["kp_y"][i]], axis=1)
        raw_err.append(np.linalg.norm((raw - expected) * px, axis=1).mean())
        smooth_err.append(np.linalg.norm((smooth - expected) * px, axis=1).mean())
        tracks_by_photo.setdefault(photo, set()).add((hands["track_id"][i], hands["handedness"][i]))
        assert hands["handedness"][i] == label
    assert np.mean(raw_err) < 3 and np.max(raw_err) < 6, (np.mean(raw_err), np.max(raw_err))
    assert np.mean(smooth_err) < 5, np.mean(smooth_err)  # smoothing lags a little while the hand moves
    # One persistent track per hand, each with the right handedness.
    assert all(len(ids) == 1 for ids in tracks_by_photo.values())
    assert len({t for ids in tracks_by_photo.values() for t, _ in ids}) == 3

    # Summaries in Postgres reference the same model version.
    tracks = db.scalars(select(HandTrack).where(HandTrack.run_id == row.id)).all()
    assert {str(t.model_version_id) for t in tracks} == {mv["id"]}
    assert sorted((t.first_frame, t.last_frame) for t in tracks) == [(0, 44), (57, 101), (102, 146)]
    assert all(t.frames_detected == 45 and t.missing_detections == 0 for t in tracks)

    # The timeline's hand track shows one segment per track, labelled with confidence and model version.
    tl = client.get(f"/api/v1/videos/{video_id}/timeline", headers=h).json()
    hand_track = next(t for t in tl["tracks"] if t["id"] == "hand")
    assert [(s["start"], s["end"], s["label"]) for s in hand_track["segments"]] == [
        (0, 44, "right hand"), (57, 101, "right hand"), (102, 146, "right hand"),
    ]  # fmt: skip
    auto = db.scalars(select(Annotation).where(Annotation.video_id == uuid.UUID(video_id))).all()
    assert auto and all(str(a.model_version_id) == mv["id"] and a.cv_run_id == row.id for a in auto)
    edges = {
        (e.parent_type, e.relation)
        for e in db.scalars(select(LineageEdge).where(LineageEdge.child_id == row.id))
    }
    assert edges == {("video", "input_of"), ("model_version", "model_of")}


def test_overlay_frames_and_finger_series_api(client, db, h, enqueued, clip):
    video_id = _video(client, db, h, enqueued, clip)
    run = _run(client, h, enqueued, video_id)
    frames = client.get(
        f"/api/v1/cv/runs/{run['id']}/frames", params={"frame_from": 40, "frame_to": 60}, headers=h
    ).json()
    assert [f["frame"] for f in frames["frames"]] == [40, 41, 42, 43, 44, 57, 58, 59, 60]
    hand = frames["frames"][0]["hands"][0]
    assert len(hand["keypoints"]) == 21 and {f["finger"] for f in hand["fingers"]} == set(samples_fingers())
    assert frames["model_version_id"] == run["model_version"]["id"]

    track = run["hand_tracks"][0]["track_id"]
    series = client.get(
        f"/api/v1/cv/runs/{run['id']}/series", params={"track_id": track, "buckets": 15}, headers=h
    ).json()
    assert [s["name"] for s in series["series"]] == ["wrist", *samples_fingers()]
    wrist = series["series"][0]["points"]
    assert 1 <= len(wrist) <= 15 and sum(p["n"] for p in wrist) == 45
    assert series["unit"] == "px/s" and max(p["max"] for p in wrist) > 0
    vis = client.get(f"/api/v1/cv/runs/{run['id']}/series", params={"track_id": track, "metric": "visibility"},
                     headers=h).json()  # fmt: skip
    assert all(p["mean"] == 1 for s in vis["series"] for p in s["points"])  # the hands stay inside the frame

    assert client.get(f"/api/v1/cv/runs/{run['id']}/frames", params={"frame_from": 0, "frame_to": 5000},
                      headers=h).status_code == 200  # clipped to the video  # fmt: skip
    assert client.get(f"/api/v1/cv/runs/{uuid.uuid4()}", headers=h).status_code == 404


def samples_fingers():
    return ["thumb", "index", "middle", "ring", "pinky"]


def test_two_hands_keep_separate_ids(client, db, h, enqueued, tmp_path):
    clip = samples.make_clip(tmp_path / "two.mp4", [samples.Segment("right_hands.jpg", 60, height=0.55,
                                                                    start=(0.45, 0.5), end=(0.55, 0.55))])  # fmt: skip
    run = _run(client, h, enqueued, _video(client, db, h, enqueued, clip))
    assert run["tracks"] == 2 and run["tracking_failures"] == 0
    assert {t["handedness"] for t in run["hand_tracks"]} == {"right"}  # the photo shows two right hands
    assert all(t["frames_detected"] >= 58 for t in run["hand_tracks"])


def test_swapping_the_adapter_is_configuration_only(client, db, h, enqueued, clip, monkeypatch):
    video_id = _video(client, db, h, enqueued, clip)
    first = _run(client, h, enqueued, video_id)

    # Another model's output for this video, as JSON Lines: here, the reference landmarks themselves.
    lines = []
    for frame, entry in enumerate(clip.frames):
        if entry is None:
            continue
        photo, _ = entry
        label, ref = samples.reference_landmarks(photo)
        xy = clip.expected(frame, ref, samples.photo_size(photo))
        kp = [[float(x), float(y), 0.0] for x, y in xy]
        lines.append(
            json.dumps({"frame": frame, "hands": [{"handedness": label, "confidence": 1.0, "keypoints": kp}]})
        )
    sha = client.get(f"/api/v1/videos/{video_id}", headers=h).json()["sha256"]
    storage.put_bytes("\n".join(lines).encode(), get_settings().s3_bucket_derived, f"predictions/{sha}.jsonl")

    # Swap the adapter through configuration alone.
    monkeypatch.setenv("HAND_TRACKING_ADAPTER", "keypoint-file")
    monkeypatch.setenv("HAND_TRACKING_CONFIG", json.dumps({
        "source": f"s3://{get_settings().s3_bucket_derived}/predictions/{{sha256}}.jsonl",
        "name": "reference-landmarks", "version": "mediapipe-assets",
    }))  # fmt: skip
    get_settings.cache_clear()
    try:
        info = client.get("/api/v1/cv/adapters", headers=h).json()
        assert (info["name"], info["runnable"]) == ("keypoint-file", True)
        second = _run(client, h, enqueued, video_id)
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()

    assert second["model_version"]["name"] == "reference-landmarks"
    assert second["model_version"]["id"] != first["model_version"]["id"]
    assert (second["tracks"], second["frames_with_hands"]) == (3, 135)
    row = db.get(CvRun, uuid.UUID(second["id"]))
    assert set(_parquet(row, "hands")["model_version_id"]) == {second["model_version"]["id"]}
    versions = {m.name for m in db.scalars(select(ModelVersion))}
    assert versions == {"mediapipe-hands", "reference-landmarks"}

    # The timeline now shows the newest run's hand segments only; the first run's output is kept.
    hand = next(t for t in client.get(f"/api/v1/videos/{video_id}/timeline", headers=h).json()["tracks"]
                if t["id"] == "hand")  # fmt: skip
    ids = {s["id"] for s in hand["segments"]}
    newest = {str(a.id) for a in db.scalars(select(Annotation).where(Annotation.cv_run_id == row.id,
                                                                     Annotation.category == "hand"))}  # fmt: skip
    assert ids == newest and len(ids) == 3
    old = db.scalars(select(Annotation).where(Annotation.cv_run_id == uuid.UUID(first["id"]))).all()
    assert old  # still stored


def test_run_permissions_and_validation(client, db, h, viewer, enqueued, clip, monkeypatch):
    video_id = _video(client, db, h, enqueued, clip)
    assert (
        client.post(
            "/api/v1/cv/runs", json={"video_ids": [video_id]}, headers=auth_header(viewer)
        ).status_code
        == 403
    )
    assert (
        client.post("/api/v1/cv/runs", json={"video_ids": [str(uuid.uuid4())]}, headers=h).status_code == 422
    )
    assert client.post("/api/v1/cv/runs", json={"video_ids": []}, headers=h).status_code == 422
    assert (
        client.post("/api/v1/cv/runs", json={"video_ids": [video_id], "stride": 0}, headers=h).status_code
        == 422
    )

    # A queued run has no output yet.
    queued = client.post("/api/v1/cv/runs", json={"video_ids": [video_id], "kinds": ["hand_tracking"]},
                         headers=h).json()[0]  # fmt: skip
    assert queued["status"] == "queued" and queued["model_version"] is None
    assert client.get(f"/api/v1/cv/runs/{queued['id']}/frames", headers=h).status_code == 409
    listed = client.get(
        "/api/v1/cv/runs", params={"video_id": video_id, "status": "queued"}, headers=h
    ).json()
    assert [r["id"] for r in listed["items"]] == [queued["id"]]

    # Selecting a documented stub fails the run with what's needed, not a crash elsewhere.
    monkeypatch.setenv("HAND_TRACKING_ADAPTER", "rtmpose-hands")
    get_settings.cache_clear()
    try:
        info = client.get("/api/v1/cv/adapters", headers=h).json()
        assert info["runnable"] is False and "stub" in info["error"]
        res = client.post("/api/v1/cv/runs", json={"video_ids": [video_id], "kinds": ["hand_tracking"]},
                          headers=h).json()[0]  # fmt: skip
        drain(enqueued)
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
    failed = client.get(f"/api/v1/cv/runs/{res['id']}", headers=h).json()
    assert failed["status"] == "failed" and "documented stub" in failed["error"]
    job = db.get(Job, uuid.UUID(failed["job_id"]))
    assert job.status == JobStatus.failed


def test_stride_processes_every_nth_frame(client, db, h, enqueued, clip):
    run = _run(client, h, enqueued, _video(client, db, h, enqueued, clip), stride=3)
    assert run["frames_processed"] == len(range(0, len(clip.frames), 3))
    row = db.get(CvRun, uuid.UUID(run["id"]))
    assert all(f % 3 == 0 for f in _parquet(row, "hands")["frame"])
    assert run["status"] == CvRunStatus.succeeded.value
