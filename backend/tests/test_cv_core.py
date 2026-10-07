"""Tracking, smoothing, and kinematics — model-independent parts of the hand pipeline (spec Phase 3)."""

import math

import numpy as np
import pytest

from egolabs.cv import registry
from egolabs.cv.adapters.base import AdapterError, HandDetection, HandResult
from egolabs.cv.features import TrackFeatures
from egolabs.cv.smoothing import OneEuroFilter
from egolabs.cv.tracking import HandTracker, TrackerConfig


def hand(x: float, y: float, handedness="right", size=0.1, z=0.0) -> HandDetection:
    """A flat open hand: wrist at (x, y), fingers pointing up."""
    kp = np.zeros((21, 3), dtype=np.float32)
    kp[0] = (x, y, 0)
    for f, dx in enumerate((-0.4, -0.2, 0.0, 0.2, 0.4)):
        for j in range(4):
            kp[1 + f * 4 + j] = (x + dx * size, y - size * (0.3 + 0.25 * j), z)
    return HandDetection(handedness=handedness, handedness_score=0.9, confidence=0.9, keypoints=kp)


def frames(*hands_per_frame):
    return [HandResult(i, i / 30, list(h)) for i, h in enumerate(hands_per_frame)]


# --- tracking ----------------------------------------------------------------------------------------


def test_ids_persist_while_hands_move_and_cross_sides():
    tracker = HandTracker()
    ids = []
    for i in range(60):
        left = hand(0.2 + i * 0.004, 0.6, "left")
        right = hand(0.8 - i * 0.004, 0.6, "right")
        ids.append(
            {t.detection.handedness: t.track_id for t in tracker.update(HandResult(i, i / 30, [right, left]))}
        )
    assert {tuple(sorted(d.values())) for d in ids} == {(1, 2)}
    assert all(d["left"] == ids[0]["left"] for d in ids)
    assert tracker.finish().failures == []


def test_short_dropouts_are_missing_detections_not_new_tracks():
    tracker = HandTracker(TrackerConfig(max_missed=5))
    seq = [[hand(0.5, 0.5)]] * 10 + [[]] * 3 + [[hand(0.51, 0.5)]] * 5
    ids = {t.track_id for r in frames(*seq) for t in tracker.update(r)}
    summary = tracker.finish()
    assert ids == {1}
    assert summary.missing == {1: 3}
    assert summary.failures == []


def test_losing_and_reacquiring_a_hand_is_a_tracking_failure():
    tracker = HandTracker(TrackerConfig(max_missed=3, reacquire_frames=30))
    seq = [[hand(0.5, 0.5)]] * 10 + [[]] * 8 + [[hand(0.52, 0.5)]] * 5
    ids = [t.track_id for r in frames(*seq) for t in tracker.update(r)]
    summary = tracker.finish()
    assert sorted(set(ids)) == [1, 2]
    assert len(summary.failures) == 1
    f = summary.failures[0]
    assert (f.lost_track_id, f.new_track_id, f.frame) == (1, 2, 18)


def test_a_hand_appearing_elsewhere_is_a_new_track_not_a_failure():
    tracker = HandTracker(TrackerConfig(max_missed=3))
    seq = [[hand(0.1, 0.5)]] * 5 + [[]] * 10 + [[hand(0.9, 0.5)]] * 5
    for r in frames(*seq):
        tracker.update(r)
    assert tracker.finish().failures == []


# --- smoothing ---------------------------------------------------------------------------------------


def test_one_euro_removes_jitter_but_follows_motion():
    rng = np.random.default_rng(0)
    still = OneEuroFilter()
    noisy = [100 + rng.normal(0, 2, size=2) for _ in range(120)]
    out = np.array([still(x, i / 30) for i, x in enumerate(noisy)])
    assert out[30:].std(axis=0).max() < np.array(noisy)[30:].std(axis=0).min() / 2

    moving = OneEuroFilter()
    ramp = [np.array([i * 20.0, 0.0]) for i in range(60)]  # 600 px/s
    out = np.array([moving(x, i / 30) for i, x in enumerate(ramp)])
    assert abs(out[-1][0] - ramp[-1][0]) < 20  # lags less than one frame of motion at speed


# --- features ----------------------------------------------------------------------------------------


def test_wrist_speed_direction_and_path_in_source_pixels():
    feats = TrackFeatures(1, width=1000, height=500)
    rows = [feats.step(i, i / 10, hand(0.1 + 0.01 * i, 0.5))[0] for i in range(40)]
    # 0.01 of the width per 0.1 s = 10 px per 0.1 s = 100 px/s, moving right.
    assert rows[-1].wrist_speed == pytest.approx(100, rel=0.05)
    assert rows[-1].direction_deg == pytest.approx(0, abs=2) or rows[-1].direction_deg == pytest.approx(
        360, abs=2
    )
    assert rows[-1].displacement_px == pytest.approx(rows[-1].path_length_px, rel=0.01)
    assert rows[0].wrist_speed == 0


def test_finger_orientation_visibility_and_occlusion():
    feats = TrackFeatures(1, width=640, height=480)
    _, fingers = feats.step(0, 0.0, hand(0.5, 0.5))
    by = {f.finger: f for f in fingers}
    assert set(by) == {"thumb", "index", "middle", "ring", "pinky"}
    assert by["middle"].orientation_deg == pytest.approx(270, abs=1)  # pointing up the image
    assert all(f.visibility == 1 and not f.occluded for f in fingers)

    edge = TrackFeatures(2, 640, 480)
    _, fingers = edge.step(0, 0.0, hand(0.5, 0.05, size=0.2))  # fingertips above the frame
    assert {f.finger: f.visibility for f in fingers}["middle"] < 1

    curled = hand(0.5, 0.6)
    curled.keypoints[12] = (0.5, 0.57, 0.05)  # middle fingertip folded back over the palm, farther away
    _, fingers = TrackFeatures(3, 640, 480).step(0, 0.0, curled)
    assert {f.finger: f.occluded for f in fingers} == {
        "thumb": False,
        "index": False,
        "middle": True,
        "ring": False,
        "pinky": False,
    }


def test_fingertip_speed_and_acceleration():
    feats = TrackFeatures(1, width=100, height=100)
    speeds = []
    for i in range(30):
        h = hand(0.5, 0.5)
        h.keypoints[8, 0] += 0.001 * i * i  # index tip accelerating to the right
        speeds.append({f.finger: f for f in feats.step(i, i / 30, h)[1]}["index"])
    assert speeds[-1].tip_speed > speeds[10].tip_speed > 0
    assert speeds[-1].tip_accel > 0
    assert math.isclose(speeds[-1].orientation_deg % 360, speeds[-1].orientation_deg)


# --- registry ----------------------------------------------------------------------------------------


def test_registry_resolves_names_and_import_paths_and_rejects_stubs():
    assert registry.resolve("keypoint-file").__name__ == "KeypointFileAdapter"
    assert (
        registry.resolve("egolabs.cv.adapters.keypoint_file:KeypointFileAdapter").__name__
        == "KeypointFileAdapter"
    )
    with pytest.raises(AdapterError, match="documented stub"):
        registry.create("rtmpose-hands", {})
    with pytest.raises(AdapterError, match="unknown adapter"):
        registry.resolve("nope")
    with pytest.raises(AdapterError, match="not a HandTrackingAdapter"):
        registry.resolve("egolabs.config:Settings")
    assert registry.config_hash("mediapipe-hands", {}) != registry.config_hash(
        "mediapipe-hands", {"num_hands": 1}
    )


# --- model assets ------------------------------------------------------------------------------------


def test_downloaded_model_is_verified_and_readable_by_other_users(tmp_path, monkeypatch):
    import hashlib
    import os
    import stat

    from egolabs.cv import assets

    src = tmp_path / "model.task"
    src.write_bytes(b"model bytes")
    good = assets.ModelAsset("model.task", src.as_uri(), hashlib.sha256(b"model bytes").hexdigest())
    monkeypatch.setattr(assets, "cache_dir", lambda: tmp_path / "cache")

    path = assets.ensure(good)
    assert path.read_bytes() == b"model bytes"
    # Images bake the model as root and run workers as another user.
    assert stat.S_IMODE(os.stat(path).st_mode) & 0o044 == 0o044
    assert assets.ensure(good) == path  # cached

    with pytest.raises(assets.AssetError, match="does not match"):
        assets.ensure(assets.ModelAsset("other.task", src.as_uri(), "0" * 64))
    assert not list((tmp_path / "cache" / ("0" * 12)).iterdir())  # no partial file left behind
