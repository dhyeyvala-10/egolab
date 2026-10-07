"""
The rule-based movement classifier on synthetic hands with exact geometry (spec Phase 4): each rule fires on
the motion it describes, not on neighbouring ones, and every event names its evidence frames with one
measurement per frame.
"""

import pytest

from egolabs.cv import registry
from egolabs.cv.adapters.base import AdapterError, VideoContext
from egolabs.cv.movement.rules import CLASSES, RuleClassifier
from tests.handgen import FPS, H, W, box, frames

VIDEO = VideoContext("v", "sha", W, H, FPS, 1000)


def classify(motion, **config):
    clf = RuleClassifier()
    clf.load(config)
    clf.reset(VIDEO)
    out = []
    for i in range(0, len(motion), 7):  # batches of any size give the same result
        out += clf.predict(motion[i : i + 7])
    out += clf.finish()
    for d in out:
        assert d.frames == sorted(d.frames) and d.frames, d
        assert all(len(v) == len(d.frames) for v in d.measurements.values()), (d.name, d.measurements)
        assert 0 <= d.confidence <= 1
    return out


def names(dets):
    return sorted(d.name for d in dets)


def still(pose, n=30, center=(320, 360), size=80.0, roll=-90.0):
    return [(pose, center, size, roll)] * n


def moving(pose, start, end, n, size=80.0, roll=-90.0, roll_end=None):
    out = []
    for i in range(n):
        u = i / max(1, n - 1)
        c = (start[0] + (end[0] - start[0]) * u, start[1] + (end[1] - start[1]) * u)
        r = roll + ((roll_end if roll_end is not None else roll) - roll) * u
        out.append((pose, c, size, r))
    return out


def test_classes_match_the_builtin_movement_classes(db):
    import importlib.util
    from pathlib import Path

    from sqlalchemy import select

    from egolabs.cv.movement.classes import BUILTIN
    from egolabs.models import MovementClass

    path = next(Path(__file__).parents[1].glob("alembic/versions/*_0005_*.py"))
    spec = importlib.util.spec_from_file_location("migration_0005", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.BUILTIN_CLASSES == BUILTIN  # the app's list is what the migration shipped
    builtin = db.scalars(select(MovementClass).where(MovementClass.builtin)).all()
    assert sorted(CLASSES) == sorted(c.name for c in builtin) and len(builtin) == 20
    assert registry.resolve("rules", "movement") is RuleClassifier


@pytest.mark.parametrize(
    ("pose", "expected", "gesture"),
    [("point", "point", None), ("victory", "gesture", "victory"), ("thumbs_up", "gesture", "thumbs_up"),
     ("fist", "gesture", "fist"), ("open", "gesture", "open_palm"), ("pinch", "pinch", None)],
)  # fmt: skip
def test_hand_poses(pose, expected, gesture):
    dets = classify(frames(still(pose, 30)))
    assert names(dets) == [expected], dets
    d = dets[0]
    assert d.frames == list(range(30)) and d.handedness == "right" and d.hand_track_id == 1
    assert d.attributes.get("gesture") == gesture
    if expected == "pinch":
        assert d.fingers == ("thumb", "index") and max(d.measurements["thumb_index_distance"]) < 0.3
        assert d.thresholds["pinch_distance"] == 0.3
    if expected == "point":
        assert d.fingers == ("index",) and min(d.measurements["index_straightness"]) >= 0.9


def test_a_pose_held_too_briefly_is_not_an_event():
    assert classify(frames(still("relaxed", 20) + still("victory", 6) + still("relaxed", 20))) == []


def test_a_moving_hand_is_not_a_gesture():
    # The victory sign waved across the frame: a swipe, not a static gesture.
    dets = classify(frames(moving("victory", (60, 360), (580, 360), 12)))
    assert names(dets) == ["swipe"]


def test_swipe_direction_and_distance():
    dets = classify(frames(still("relaxed", 10, (560, 300)) + moving("relaxed", (560, 300), (120, 310), 12)
                           + still("relaxed", 10, (120, 310))))  # fmt: skip
    (swipe,) = [d for d in dets if d.name == "swipe"]
    assert swipe.attributes["direction"] == "left" and swipe.attributes["distance_px"] > 0.2 * W
    assert swipe.start_frame >= 10 and swipe.end_frame <= 22
    assert min(swipe.measurements["wrist_speed_px_s"]) >= 0.6 * W


def test_a_slow_move_is_not_a_swipe():
    assert "swipe" not in names(classify(frames(moving("relaxed", (120, 300), (560, 300), 120))))


def test_rotate_clockwise_and_back():
    motion = (still("relaxed", 10) + moving("relaxed", (320, 360), (320, 360), 20, roll=-90, roll_end=0)
              + still("relaxed", 10, roll=0) + moving("relaxed", (320, 360), (320, 360), 20, roll=0, roll_end=-90))  # fmt: skip
    rot = [d for d in classify(frames(motion)) if d.name == "rotate"]
    assert [r.attributes["direction"] for r in rot] == ["clockwise", "counterclockwise"]
    assert all(80 <= r.attributes["degrees"] <= 95 for r in rot), rot
    assert abs(rot[0].measurements["roll_turned_deg"][-1] - rot[0].attributes["degrees"]) < 0.01


def test_hand_enters_and_exits_at_the_frame_edges():
    motion = [None] * 10 + moving("relaxed", (635, 300), (400, 300), 20) + still("relaxed", 10, (400, 300)) \
        + moving("relaxed", (400, 300), (40, 300), 20) + [None] * 30  # fmt: skip
    dets = classify(frames(motion))
    enter = next(d for d in dets if d.name == "hand_enter")
    exit_ = next(d for d in dets if d.name == "hand_exit")
    assert enter.start_frame == 10 and enter.attributes["edge"] == "right"
    assert exit_.end_frame == 59 and exit_.attributes["edge"] == "left"
    # A hand in view from the first frame to the last neither enters nor leaves.
    assert not {"hand_enter", "hand_exit"} & set(names(classify(frames(still("relaxed", 40)))))


def test_a_hand_appearing_mid_view_enters_with_lower_confidence():
    mid = next(d for d in classify(frames([None] * 5 + still("relaxed", 20))) if d.name == "hand_enter")
    edge = next(
        d for d in classify(frames([None] * 5 + still("relaxed", 20, (636, 300)))) if d.name == "hand_enter"
    )
    assert mid.attributes["edge"] is None and mid.confidence < edge.confidence


CUP = (250, 200, 80, 100)  # centre x, y, width, height (px)


def _touching_point(cup=CUP):
    """Wrist position that puts a pointing index tip just inside the top-right of the cup's box."""
    from tests.handgen import place

    kp = place("point", (0, 0))
    tip = kp[8, :2] * [W, H]
    return (cup[0] + cup[2] / 2 - 10 - tip[0], cup[1] - cup[3] / 2 + 15 - tip[1])


def test_reach_then_press():
    at = _touching_point()
    start = (at[0] + 250, at[1] + 60)
    motion = (
        moving("point", start, at, 25)
        + still("point", 30, at)
        + moving("point", at, (at[0] + 250, at[1]), 40)
    )
    cup = [[box(*CUP)] for _ in motion]
    dets = classify(frames(motion, cup))
    assert names(dets) == ["press", "reach"], dets
    reach = next(d for d in dets if d.name == "reach")
    press = next(d for d in dets if d.name == "press")
    assert reach.object_track_id == 1 and reach.object_label == "cup"
    dist = reach.measurements["distance_to_object_px"]
    assert dist[0] > 150 and dist[-1] < 0.12 * 80  # ends within the contact margin of the box
    assert dist == sorted(dist, reverse=True)
    assert press.fingers == ("index",) and press.end_frame - press.start_frame >= 0.5 * FPS


def test_tap():
    at = _touching_point()
    away = (at[0] + 120, at[1])
    motion = still("point", 10, away) + still("point", 5, at) + still("point", 15, away)
    dets = [d for d in classify(frames(motion, [[box(*CUP)] for _ in motion])) if d.name != "point"]
    # A jump onto the object is no reach; the still hand pointing before and after is a point, not shown.
    assert (
        names(dets) == ["tap"] and dets[0].attributes["duration_s"] <= 0.4 and dets[0].fingers == ("index",)
    )


def _grasp_at(cup=CUP):
    """Wrist position that closes a fist over the cup's right edge (index, middle, ring fingertips on it)."""
    return (cup[0] + cup[2] / 2 - 25, cup[1] + 40)


def test_grasp_pick_up_hold_move_put_down_release():
    g = _grasp_at()
    lift, side = 80, 120
    seq, cup = [], []

    def add(poses, cups):
        seq.extend(poses)
        cup.extend(cups)

    away = (g[0] + 200, g[1])
    add(moving("fist", away, g, 20), [[box(*CUP)]] * 20)  # reach
    add(still("fist", 36, g), [[box(*CUP)]] * 36)  # grasp + hold
    for i in range(20):  # pick up: hand and cup rise together
        dy = lift * (i + 1) / 20
        add([("fist", (g[0], g[1] - dy), 80.0, -90.0)], [[box(CUP[0], CUP[1] - dy, CUP[2], CUP[3])]])
    for i in range(20):  # move sideways
        dx = side * (i + 1) / 20
        add(
            [("fist", (g[0] - dx, g[1] - lift), 80.0, -90.0)],
            [[box(CUP[0] - dx, CUP[1] - lift, CUP[2], CUP[3])]],
        )
    for i in range(20):  # put down
        dy = lift * (1 - (i + 1) / 20)
        add(
            [("fist", (g[0] - side, g[1] - dy), 80.0, -90.0)],
            [[box(CUP[0] - side, CUP[1] - dy, CUP[2], CUP[3])]],
        )
    end = (g[0] - side, g[1])
    add(moving("open", end, (end[0] + 250, end[1]), 30), [[box(CUP[0] - side, CUP[1], CUP[2], CUP[3])]] * 30)
    dets = classify(frames(seq, cup))
    order = [d.name for d in sorted(dets, key=lambda d: d.start_frame) if d.name != "gesture"]
    assert order == ["reach", "grasp", "hold", "pick_up", "move", "put_down", "release"], order
    pick = next(d for d in dets if d.name == "pick_up")
    ys = pick.measurements["object_center_y_px"]
    assert ys[0] - ys[-1] >= 0.06 * H and pick.attributes["lift_px"] > 0
    assert next(d for d in dets if d.name == "move").attributes["direction"] == "left"
    assert all(d.object_label == "cup" for d in dets if d.name != "gesture")


def test_push_and_pull_change_the_hand_size_while_touching():
    at = _touching_point()
    shrink = [("point", at, 80.0 - 20 * i / 19, -90.0) for i in range(20)]
    for motion, expected in ((still("point", 5, at, size=80.0) + shrink, "push"),
                             (still("point", 5, at, size=60.0) + shrink[::-1], "pull")):  # fmt: skip
        dets = classify(frames(motion, [[box(250, 200, 200, 200)] for _ in motion]))
        (d,) = [x for x in dets if x.name in ("push", "pull")]
        assert d.name == expected and d.measurements["hand_size_px"]


def test_drag_moves_the_object_with_a_fingertip():
    at = _touching_point()
    seq = [("point", (at[0] - 4 * i, at[1]), 80.0, -90.0) for i in range(30)]
    cups = [[box(CUP[0] - 4 * i, CUP[1], CUP[2], CUP[3])] for i in range(30)]
    dets = classify(frames(seq, cups))
    assert (
        "drag" in names(dets) and next(d for d in dets if d.name == "drag").attributes["direction"] == "left"
    )


def test_manipulate_is_finger_work_with_a_still_wrist():
    g = _grasp_at()
    busy = [dict.fromkeys(("thumb", "index", "middle", "ring", "pinky"), 200.0)] * 30
    dets = classify(frames(still("fist", 30, g), [[box(*CUP)]] * 30, tip_speed=busy))
    assert "manipulate" in names(dets)


def test_no_contact_rules_without_objects():
    motion = moving("fist", (560, 300), (300, 300), 20) + still("fist", 30, (300, 300))
    assert not set(names(classify(frames(motion)))) & {"reach", "grasp", "hold", "release", "press", "tap"}


def test_thresholds_are_configuration():
    open_hand = frames(still("open", 30))
    assert names(classify(open_hand)) == ["gesture"]
    assert names(classify(open_hand, pinch_distance=1.2)) == ["pinch"]  # a looser pinch takes the open hand
    with pytest.raises(AdapterError, match="unknown rules options"):
        RuleClassifier().load({"nope": 1})


def test_a_hand_picked_up_under_a_new_track_id_is_no_exit_or_entrance():
    from egolabs.cv.movement.base import MotionFrame

    first = frames(still("relaxed", 20, (300, 300)))
    second = frames(still("relaxed", 20, (310, 300)))
    for f in second:  # the tracker lost the hand and found it again at once, under ID 2
        f.index += 21
        f.timestamp_s = f.index / FPS
        for hand in f.hands:
            hand.track_id = 2
        for ct in f.contacts:
            ct.hand_track_id = 2
    gap = [MotionFrame(20, 20 / FPS)]
    motion = (
        [MotionFrame(0, 0.0)]
        + first[1:]
        + gap
        + second
        + [MotionFrame(41 + i, (41 + i) / FPS) for i in range(30)]
    )
    dets = classify(motion)
    enters = [d for d in dets if d.name == "hand_enter"]
    exits = [d for d in dets if d.name == "hand_exit"]
    assert [d.hand_track_id for d in enters] == [1] and [d.hand_track_id for d in exits] == [2], dets
    # Far away, it's another hand: that one enters.
    far = frames(still("relaxed", 20, (300, 300))) + frames(still("relaxed", 20, (80, 100)))
    for f in far[20:]:
        f.index += 20
        f.timestamp_s = f.index / FPS
        for hand in f.hands:
            hand.track_id = 2
    assert (
        len([d for d in classify(far) if d.name == "hand_enter"]) == 1
    )  # track 2 (track 1 was there from frame 0)


def test_short_spurious_tracks_make_no_events():
    motion = still("relaxed", 30, (300, 300))
    dets = classify(frames([None] * 10 + still("point", 5, (500, 300)) + [None] * 40))
    assert dets == []
    assert classify(frames(motion)) == []
