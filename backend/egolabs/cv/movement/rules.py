"""
The rule-based movement classifier (`MOVEMENT_CLASSIFIER_ADAPTER=rules`).

Every class is an explicit rule over one hand track's keypoints, kinematics, and contact with objects. Each
event keeps the frames the rule looked at and the values it compared (`measurements`) against its
`thresholds`, so a reviewer can see exactly why it fired. Distances are in source pixels, scaled by the
hand's size (wrist to middle knuckle) or the frame; times are in seconds, so the rules hold at any frame
rate or stride. Every threshold is configurable through `MOVEMENT_CLASSIFIER_CONFIG`.

Hand pose, per frame (finger straightness = tip-to-base distance ÷ the finger's joint-path length; reach =
tip-to-wrist ÷ second-joint-to-wrist):
- extended: straightness ≥ `extended_straightness` and reach ≥ `extended_reach`
- curled: straightness ≤ `curled_straightness` or reach ≤ `curled_reach`

Rules without objects:
- hand_enter / hand_exit — a track starts after the first frame / ends before the last; the first/last
  `enter_exit_s` of it is the evidence. Mid-view appearances score lower than ones at a frame edge, and a
  track that starts within `handoff_s` and `handoff_distance` hand sizes of where a same-handed one stopped
  is the same hand under a new ID (a tracking failure): no exit, no entrance.

Tracks shorter than `min_track_s` produce no events (spurious detections).
- pinch — thumb–index tip distance < `pinch_distance` hand sizes, index not curled, for `pinch_min_s`.
- point — a still hand (< `still_speed` hand sizes/s), index extended and middle/ring/pinky curled, not
  touching anything or pinching, for `pose_min_s`.
- gesture — a still, non-pinching hand (< `still_speed` hand sizes/s) holding victory, thumbs up/down, open palm, or
  fist, away from objects, for `gesture_min_s`.
- swipe — wrist faster than `swipe_speed` frame widths/s, covering ≥ `swipe_distance` frame widths along a
  straight path (net/total ≥ `swipe_straightness`) within `swipe_max_s`.
- rotate — the hand's roll (wrist → middle knuckle) turning ≥ `rotate_rate` °/s one way, for a total of
  ≥ `rotate_degrees` within `rotate_max_s`.

Rules on contact episodes (a hand touching one object, gaps ≤ `contact_gap_s`):
- reach — in the `reach_window_s` before contact, the nearest fingertip closes ≥ `reach_distance` frame
  widths on the object.
- grasp episodes (≥ `grasp_share` of frames with ≥ `grasp_curled` of the four fingers curled and the index
  not extended):
  grasp (its first `grasp_s`), release (its last `grasp_s`, if the hand lets go before the video ends),
  pick_up / put_down (object centre rising / falling faster than `lift_speed` frame heights/s by ≥
  `lift_distance`), move (object carried sideways faster than `carry_speed` by ≥ `carry_distance` frame
  widths), hold (hand and object still for ≥ `hold_min_s`).
- touch episodes (not grasping): tap (contact ≤ `tap_max_s`), press (a still fingertip for ≥
  `press_min_s`), drag (hand moves ≥ `drag_distance` frame widths sideways and the object follows). Their
  fingers are the fingertips on the object that aren't curled into the palm.

Motion within an episode is judged per frame from the object centre's velocity over `phase_window_s`;
interruptions up to `phase_gap_s` don't split a phase.
- either: push / pull (hand size shrinks / grows by ≥ `depth_change` — moving away from / toward the
  camera), manipulate (wrist still while the fingertips move ≥ `manipulate_speed` hand sizes/s for
  ≥ `manipulate_min_s`).

Confidence = mean hand-model confidence over the evidence frames × a rule margin in [0.5, 1] (how far past
its threshold the rule was), × the mean contact score for rules that need an object.
"""

import math
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from egolabs.cv.adapters.base import AdapterError, AdapterMetadata, VideoContext
from egolabs.cv.keypoints import FINGERS
from egolabs.cv.movement.base import Contact, MotionFrame, MovementClassifier, MovementDetection, ObjectState
from egolabs.cv.movement.contact import TIPS, box_px, distance_to_box, hand_size, to_px

VERSION = "egolabs-rules-1"
FINGER_NAMES = tuple(FINGERS)
FOUR = ("index", "middle", "ring", "pinky")
GESTURES = ("victory", "thumbs_up", "thumbs_down", "open_palm", "fist")
CLASSES = (
    "hand_enter", "hand_exit", "reach", "grasp", "release", "pinch", "point", "tap", "swipe", "rotate",
    "push", "pull", "pick_up", "put_down", "hold", "move", "manipulate", "press", "drag", "gesture",
)  # fmt: skip

DEFAULTS: dict[str, float] = {
    "extended_straightness": 0.9,
    "extended_reach": 1.15,
    "curled_straightness": 0.7,
    "curled_reach": 0.85,
    "gap_s": 0.15,  # a condition may drop out this long without ending its run
    "pinch_distance": 0.3,
    "pinch_index_straightness": 0.6,
    "pinch_min_s": 0.2,
    "pose_min_s": 0.3,
    "gesture_min_s": 0.4,
    "still_speed": 1.5,
    "swipe_speed": 0.6,
    "swipe_distance": 0.2,
    "swipe_straightness": 0.8,
    "swipe_max_s": 1.0,
    "rotate_rate": 60.0,
    "rotate_degrees": 45.0,
    "rotate_max_s": 3.0,
    "edge_margin": 0.04,
    "track_end_s": 0.5,
    "min_track_s": 0.3,  # events of hand tracks shorter than this are dropped (spurious detections)
    "handoff_s": 0.2,  # a same-handed track starting within this long of one stopping…
    "handoff_distance": 1.5,  # …and this many hand sizes from where it stopped is the same hand (a hand-off)
    "enter_exit_s": 0.2,
    "contact_gap_s": 0.3,
    "grasp_curled": 3,
    "grasp_share": 0.5,
    "grasp_s": 0.2,
    "reach_window_s": 1.5,
    "reach_distance": 0.08,
    "tap_max_s": 0.4,
    "press_min_s": 0.5,
    "hold_min_s": 1.0,
    "phase_window_s": 0.4,
    "phase_gap_s": 0.2,  # a phase may be interrupted this long (detector jitter) without ending
    "lift_speed": 0.08,
    "lift_distance": 0.06,
    "carry_speed": 0.08,
    "carry_distance": 0.08,
    "drag_distance": 0.08,
    "depth_change": 0.15,
    "manipulate_speed": 1.0,
    "manipulate_min_s": 0.6,
}


@dataclass
class _S:
    """One hand in one frame, with everything the rules look at."""

    frame: int
    t: float
    conf: float
    px: np.ndarray  # 21×3 pixels
    size: float
    wrist: np.ndarray
    speed: float  # wrist, px/s
    straight: dict[str, float]
    reach: dict[str, float]
    extended: frozenset[str]
    curled: frozenset[str]
    pose: str | None
    pinch: float  # thumb–index tip distance / hand size
    roll: float  # degrees, image coordinates (y down)
    rel_tip: float  # mean fingertip speed beyond the wrist's, hand sizes/s
    edge: str | None  # frame edge the hand touches
    contact: Contact | None = None
    obj: ObjectState | None = None
    grasping: bool = False
    roll_delta: float = 0.0  # ° turned since the previous sample of this track
    roll_rate: float = 0.0  # °/s over that step


@dataclass
class _Run:
    key: tuple[Any, ...]
    samples: list[_S] = field(default_factory=list)
    before: list[_S] = field(default_factory=list)  # track history when the run opened (for reach)


@dataclass
class _Track:
    track_id: int
    handedness: str
    first: _S
    history: deque[_S]
    last: _S
    runs: dict[tuple[Any, ...], _Run] = field(default_factory=dict)
    entered: bool = False
    opening: list[_S] = field(default_factory=list)
    handed_off: bool = False  # the hand carried on under another track ID: no exit
    pending: list[MovementDetection] = field(default_factory=list)  # held until the track proves real
    confirmed: bool = False


def _clip(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _wrap(deg: float) -> float:
    return (deg + 180.0) % 360.0 - 180.0


class RuleClassifier(MovementClassifier):
    classes = CLASSES

    def __init__(self) -> None:
        self.c: dict[str, float] = dict(DEFAULTS)
        self.width = self.height = 0
        self._tracks: dict[int, _Track] = {}
        self._out: list[MovementDetection] = []
        self._first_frame: int | None = None
        self._last_t = 0.0

    # --- adapter interface -----------------------------------------------------------------------

    def load(self, config: dict[str, Any]) -> None:
        unknown = set(config) - set(DEFAULTS)
        if unknown:
            raise AdapterError(f"unknown rules options: {', '.join(sorted(unknown))}")
        try:
            self.c = {**DEFAULTS, **{k: float(v) for k, v in config.items()}}
        except (TypeError, ValueError) as exc:
            raise AdapterError(f"rules options must be numbers: {exc}") from exc

    def metadata(self) -> AdapterMetadata:
        return AdapterMetadata(name="rules", version=VERSION, labels=list(CLASSES))

    def reset(self, video: VideoContext | None = None) -> None:
        if video is None or not (video.width and video.height):
            raise AdapterError("the rules classifier needs the video's resolution")
        self.width, self.height = video.width, video.height
        self._tracks, self._out, self._first_frame, self._last_t = {}, [], None, 0.0

    def predict(self, frames: Sequence[MotionFrame]) -> list[MovementDetection]:
        for frame in frames:
            self._frame(frame)
        out, self._out = self._out, []
        return out

    def finish(self) -> list[MovementDetection]:
        for track in list(self._tracks.values()):
            ends_early = track.last.t < self._last_t - self.c["track_end_s"]
            self._end_track(track, video_end=not ends_early)
        out, self._out = self._out, []
        return out

    # --- per frame ---------------------------------------------------------------------------------

    def _sample(
        self, frame: MotionFrame, hand: Any, contacts: dict[int, Contact], objects: dict[int, ObjectState]
    ) -> _S:
        c = self.c
        px = to_px(hand.keypoints, self.width, self.height)
        size = max(hand_size(px), 1.0)
        straight, reach = {}, {}
        for name, joints in FINGERS.items():
            j = list(joints)
            path = sum(float(np.linalg.norm(px[j[k + 1]] - px[j[k]])) for k in range(3))
            straight[name] = float(np.linalg.norm(px[j[3]] - px[j[0]])) / max(path, 1e-6)
            reach[name] = float(np.linalg.norm(px[j[3]] - px[0])) / max(
                float(np.linalg.norm(px[j[1]] - px[0])), 1e-6
            )
        extended = frozenset(
            n
            for n in FINGER_NAMES
            if straight[n] >= c["extended_straightness"] and reach[n] >= c["extended_reach"]
        )
        curled = frozenset(
            n
            for n in FINGER_NAMES
            if straight[n] <= c["curled_straightness"] or reach[n] <= c["curled_reach"]
        )
        wrist = px[0, :2]
        speed = float(np.hypot(*hand.wrist_velocity))
        tips = [hand.tip_speed.get(n, 0.0) for n in FINGER_NAMES]
        rel = float(np.mean([max(0.0, s - speed) for s in tips])) / size
        norm = hand.keypoints[:, :2]
        m = c["edge_margin"]
        edge = None
        for name, hit in (("left", norm[:, 0].min() <= m), ("right", norm[:, 0].max() >= 1 - m),
                          ("top", norm[:, 1].min() <= m), ("bottom", norm[:, 1].max() >= 1 - m)):  # fmt: skip
            if hit:
                edge = name
                break
        contact = contacts.get(hand.track_id)
        obj = objects.get(contact.object_track_id) if contact else None
        s = _S(
            frame=frame.index, t=frame.timestamp_s, conf=float(hand.confidence), px=px, size=size, wrist=wrist,
            speed=speed, straight=straight, reach=reach, extended=extended, curled=curled,
            pose=self._pose(extended, curled, px, size), pinch=float(np.linalg.norm(px[4, :2] - px[8, :2])) / size,
            roll=math.degrees(math.atan2(px[9, 1] - px[0, 1], px[9, 0] - px[0, 0])), rel_tip=rel, edge=edge,
            contact=contact, obj=obj,
        )  # fmt: skip
        # A closed hand on the object; a pointing hand touching with its index is a touch, not a grasp.
        s.grasping = (
            contact is not None
            and "index" not in extended
            and sum(f in curled for f in FOUR) >= c["grasp_curled"]
        )
        return s

    @staticmethod
    def _pose(ext: frozenset[str], cur: frozenset[str], px: np.ndarray, size: float) -> str | None:
        if ext >= set(FINGER_NAMES):
            return "open_palm"
        if "index" in ext and cur >= {"middle", "ring", "pinky"}:
            return "point"
        if ext >= {"index", "middle"} and cur >= {"ring", "pinky"}:
            return "victory"
        if "thumb" in ext and cur >= set(FOUR):
            rise = px[2, 1] - px[4, 1]  # thumb knuckle to tip, upward positive
            if rise > 0.5 * size:
                return "thumbs_up"
            if rise < -0.5 * size:
                return "thumbs_down"
        if cur >= set(FOUR) and "thumb" not in ext:
            return "fist"
        return None

    def _frame(self, frame: MotionFrame) -> None:
        if self._first_frame is None:
            self._first_frame = frame.index
        self._last_t = frame.timestamp_s
        best: dict[int, Contact] = {}
        for ct in frame.contacts:  # a hand's contact is with the object it touches most
            if ct.hand_track_id not in best or ct.score > best[ct.hand_track_id].score:
                best[ct.hand_track_id] = ct
        objects = {o.track_id: o for o in frame.objects}
        seen = set()
        for hand in frame.hands:
            seen.add(hand.track_id)
            s = self._sample(frame, hand, best, objects)
            track = self._tracks.get(hand.track_id)
            if track is None:
                track = _Track(hand.track_id, hand.handedness, s, deque(), s)
                self._tracks[hand.track_id] = track
            else:
                dt = s.t - track.last.t
                s.roll_delta = _wrap(s.roll - track.last.roll)
                s.roll_rate = s.roll_delta / dt if dt > 0 else 0.0
            self._step(track, s)
            track.last = s
            track.history.append(s)
            while track.history and s.t - track.history[0].t > self.c["reach_window_s"]:
                track.history.popleft()
        for tid, track in list(self._tracks.items()):
            if tid not in seen:
                for key, run in list(track.runs.items()):
                    if frame.timestamp_s - run.samples[-1].t > self._gap(key):
                        self._close(track, key)
                if frame.timestamp_s - track.last.t > self.c["track_end_s"]:
                    self._end_track(track, video_end=False)

    def _handed_off(self, new: _Track) -> bool:
        """
        Whether `new` is a hand that another same-handed track was following until just before (or as) it
        started, near where it started — the same hand under a new ID (a Phase 3 tracking failure). Judged
        once that other track has gone, so two hands side by side aren't mistaken for one.
        """
        c, s = self.c, new.first
        for old in self._tracks.values():
            if old is new or old.handed_off or old.handedness != new.handedness or old.first.t >= s.t:
                continue
            gone = old.last.t < self._last_t
            recent = s.t - c["handoff_s"] <= old.last.t <= s.t + c["handoff_s"]
            near = float(np.linalg.norm(old.last.wrist - s.wrist)) <= c["handoff_distance"] * max(
                old.last.size, s.size
            )
            if gone and recent and near:
                old.handed_off = True
                return True
        return False

    def _gap(self, key: tuple[Any, ...]) -> float:
        return self.c["contact_gap_s"] if key[0] == "contact" else self.c["gap_s"]

    def _step(self, track: _Track, s: _S) -> None:
        c = self.c
        if not track.confirmed and s.t - track.first.t >= c["min_track_s"]:
            track.confirmed = True
            self._out += track.pending
            track.pending = []
        if not track.entered:
            track.opening.append(s)
            if s.t - track.first.t >= c["enter_exit_s"]:
                self._enter(track)
        active: set[tuple[Any, ...]] = set()
        pinching = s.pinch < c["pinch_distance"] and s.straight["index"] >= c["pinch_index_straightness"]
        if pinching:
            active.add(("pinch",))
        elif s.contact is None and s.speed < c["still_speed"] * s.size:  # held poses, away from objects
            if s.pose == "point":
                active.add(("point",))
            elif s.pose in GESTURES:
                active.add(("gesture", s.pose))
        if s.speed >= c["swipe_speed"] * self.width:
            active.add(("swipe",))
        if abs(s.roll_rate) >= c["rotate_rate"]:
            active.add(("rotate", 1 if s.roll_rate > 0 else -1))
        if s.contact is not None:
            active.add(("contact", s.contact.object_track_id))
        for key in list(track.runs):
            if key not in active and s.t - track.runs[key].samples[-1].t > self._gap(key):
                self._close(track, key)
        for key in active:
            run = track.runs.get(key)
            if run is None:
                run = track.runs[key] = _Run(key, before=list(track.history) if key[0] == "contact" else [])
            run.samples.append(s)

    # --- closing runs ------------------------------------------------------------------------------

    def _close(self, track: _Track, key: tuple[Any, ...], video_end: bool = False) -> None:
        run = track.runs.pop(key)
        kind = key[0]
        if kind == "contact":
            self._episode(track, run, video_end)
        elif kind == "pinch":
            self._pinch(track, run)
        elif kind == "point":
            self._point(track, run)
        elif kind == "gesture":
            self._gesture(track, run)
        elif kind == "swipe":
            self._swipe(track, run)
        elif kind == "rotate":
            self._rotate(track, run)

    def _enter(self, track: _Track) -> None:
        track.entered = True
        if self._first_frame is None or track.first.frame <= self._first_frame:
            return  # in view from the start
        if self._handed_off(track):
            return
        ss = track.opening
        edge = ss[0].edge
        self._emit("hand_enter", track, ss, 1.0 if edge else 0.2, attributes={"edge": edge},
                   measurements={"wrist_x_px": [float(s.wrist[0]) for s in ss],
                                 "wrist_y_px": [float(s.wrist[1]) for s in ss]},
                   rule="track starts after the first frame" + (f", at the {edge} edge" if edge else " mid-view"))  # fmt: skip

    def _end_track(self, track: _Track, video_end: bool) -> None:
        if not track.entered:
            self._enter(track)
        for key, run in list(track.runs.items()):
            # Cut off by the end of the video only if it lasted to the hand's last frame.
            self._close(track, key, video_end=video_end and run.samples[-1].t >= track.last.t)
        self._tracks.pop(track.track_id, None)
        if track.last.t - track.first.t < self.c["min_track_s"] and not track.handed_off:
            track.pending = []  # too short to be a real hand
            return
        self._out += track.pending
        track.pending, track.confirmed = [], True
        if video_end or track.handed_off:
            return
        tail = [s for s in track.history if track.last.t - s.t <= self.c["enter_exit_s"]] or [track.last]
        edge = tail[-1].edge
        self._emit("hand_exit", track, tail, 1.0 if edge else 0.2, attributes={"edge": edge},
                   measurements={"wrist_x_px": [float(s.wrist[0]) for s in tail],
                                 "wrist_y_px": [float(s.wrist[1]) for s in tail]},
                   rule="track ends before the last frame" + (f", at the {edge} edge" if edge else " mid-view"))  # fmt: skip

    @staticmethod
    def _duration(ss: list[_S]) -> float:
        return ss[-1].t - ss[0].t if len(ss) > 1 else 0.0

    def _pinch(self, track: _Track, run: _Run) -> None:
        ss, thr = run.samples, self.c["pinch_distance"]
        if self._duration(ss) < self.c["pinch_min_s"]:
            return
        margin = float(np.mean([(thr - s.pinch) / thr for s in ss]))
        self._emit("pinch", track, ss, margin, fingers=("thumb", "index"),
                   measurements={"thumb_index_distance": [s.pinch for s in ss],
                                 "index_straightness": [s.straight["index"] for s in ss]},
                   thresholds={"pinch_distance": thr, "pinch_index_straightness": self.c["pinch_index_straightness"]},
                   rule=f"thumb–index tip distance < {thr:g} hand sizes with the index not curled")  # fmt: skip

    def _point(self, track: _Track, run: _Run) -> None:
        ss = run.samples
        if self._duration(ss) < self.c["pose_min_s"]:
            return
        margin = float(
            np.mean([_clip((s.straight["index"] - self.c["curled_straightness"]) / 0.3) for s in ss])
        )
        self._emit("point", track, ss, margin, fingers=("index",),
                   measurements={"index_straightness": [s.straight["index"] for s in ss],
                                 "curled_fingers": [float(sum(f in s.curled for f in FOUR)) for s in ss]},
                   thresholds={"extended_straightness": self.c["extended_straightness"]},
                   rule="index extended, middle/ring/pinky curled, not touching an object")  # fmt: skip

    def _gesture(self, track: _Track, run: _Run) -> None:
        ss, pose = run.samples, run.key[1]
        if self._duration(ss) < self.c["gesture_min_s"]:
            return
        still = float(np.mean([_clip(1 - s.speed / (self.c["still_speed"] * s.size)) for s in ss]))
        fingers = tuple(f for f in FINGER_NAMES if f in ss[len(ss) // 2].extended)
        self._emit("gesture", track, ss, 0.5 + 0.5 * still, fingers=fingers, attributes={"gesture": pose},
                   measurements={"wrist_speed_hand_sizes_s": [s.speed / s.size for s in ss]},
                   thresholds={"still_speed": self.c["still_speed"]},
                   rule=f"still hand holding the {pose.replace('_', ' ')} pose, away from objects")  # fmt: skip

    def _swipe(self, track: _Track, run: _Run) -> None:
        ss, c = run.samples, self.c
        dur = self._duration(ss)
        if len(ss) < 2 or dur > c["swipe_max_s"]:
            return
        net = ss[-1].wrist - ss[0].wrist
        path = sum(float(np.linalg.norm(b.wrist - a.wrist)) for a, b in zip(ss, ss[1:], strict=False))
        dist = float(np.linalg.norm(net))
        straightness = dist / path if path else 0.0
        if dist < c["swipe_distance"] * self.width or straightness < c["swipe_straightness"]:
            return
        dx, dy = float(net[0]), float(net[1])
        direction = ("right" if dx > 0 else "left") if abs(dx) >= abs(dy) else ("down" if dy > 0 else "up")
        margin = _clip(dist / (c["swipe_distance"] * self.width) - 1) * 0.5 + 0.5 * straightness
        self._emit("swipe", track, ss, margin,
                   attributes={"direction": direction, "distance_px": round(dist, 1), "straightness": round(straightness, 3)},
                   measurements={"wrist_speed_px_s": [s.speed for s in ss], "wrist_x_px": [float(s.wrist[0]) for s in ss],
                                 "wrist_y_px": [float(s.wrist[1]) for s in ss]},
                   thresholds={"swipe_speed_px_s": c["swipe_speed"] * self.width,
                               "swipe_distance_px": c["swipe_distance"] * self.width,
                               "swipe_straightness": c["swipe_straightness"]},
                   rule=f"fast straight sweep of ≥ {c['swipe_distance']:g} frame widths within {c['swipe_max_s']:g} s")  # fmt: skip

    def _rotate(self, track: _Track, run: _Run) -> None:
        ss, c = run.samples, self.c
        if len(ss) < 2 or self._duration(ss) > c["rotate_max_s"]:
            return
        # Roll turned through the run: the steps into each of its frames, and the running total.
        rolls = list(np.cumsum([s.roll_delta for s in ss]))
        total = float(rolls[-1])
        if abs(total) < c["rotate_degrees"]:
            return
        # In image coordinates (y down) a growing angle turns clockwise on screen.
        direction = "clockwise" if total > 0 else "counterclockwise"
        self._emit("rotate", track, ss, _clip(abs(total) / c["rotate_degrees"] - 1) * 0.5 + 0.5,
                   attributes={"direction": direction, "degrees": round(abs(total), 1)},
                   measurements={"roll_turned_deg": rolls, "roll_rate_deg_s": [s.roll_rate for s in ss]},
                   thresholds={"rotate_rate": c["rotate_rate"], "rotate_degrees": c["rotate_degrees"]},
                   rule=f"hand roll turning ≥ {c['rotate_rate']:g}°/s, ≥ {c['rotate_degrees']:g}° in all")  # fmt: skip

    # --- contact episodes --------------------------------------------------------------------------

    def _center(self, s: _S) -> np.ndarray:
        assert s.obj is not None
        x0, y0, x1, y1 = box_px(s.obj.bbox, self.width, self.height)
        return np.array([(x0 + x1) / 2, (y0 + y1) / 2])

    def _phases(self, ss: list[_S], label) -> list[tuple[str, list[_S]]]:
        """
        Consecutive samples grouped by `label(i)`. A stretch of other labels no longer than `phase_gap_s`
        between two samples of the same label joins that phase (detector jitter shouldn't split a motion).
        """
        labels = [label(i) for i in range(len(ss))]
        i = 0
        while i < len(ss):
            if labels[i] is None or i + 1 >= len(ss) or labels[i + 1] == labels[i]:
                i += 1
                continue
            j = i + 1
            while j < len(ss) and labels[j] != labels[i] and ss[j].t - ss[i].t <= self.c["phase_gap_s"]:
                j += 1
            if j < len(ss) and labels[j] == labels[i] and ss[j].t - ss[i].t <= self.c["phase_gap_s"] + 1e-9:
                for k in range(i + 1, j):
                    labels[k] = labels[i]
            i += 1
        out: list[tuple[str, list[_S]]] = []
        for s, lab in zip(ss, labels, strict=True):
            if lab is None:
                out.append(("", []))
            elif out and out[-1][0] == lab:
                out[-1][1].append(s)
            else:
                out.append((lab, [s]))
        return [(lab, group) for lab, group in out if lab and group]

    def _velocity(self, ss: list[_S], i: int, point) -> np.ndarray:
        """Central-difference velocity (px/s) of `point(sample)` over ±phase_window/2 around sample i."""
        half = self.c["phase_window_s"] / 2
        lo = i
        while lo > 0 and ss[i].t - ss[lo - 1].t <= half:
            lo -= 1
        hi = i
        while hi < len(ss) - 1 and ss[hi + 1].t - ss[i].t <= half:
            hi += 1
        dt = ss[hi].t - ss[lo].t
        return (point(ss[hi]) - point(ss[lo])) / dt if dt > 0 else np.zeros(2)

    def _episode(self, track: _Track, run: _Run, video_end: bool) -> None:
        c, ss = self.c, run.samples
        obj_id = int(run.key[1])
        label = ss[0].obj.label if ss[0].obj else None
        touching = tuple(f for f in FINGER_NAMES if any(s.contact and f in s.contact.fingers for s in ss))
        # For a touch, the fingers doing it: fingertips on the object that aren't curled into the palm.
        working = tuple(f for f in touching if sum(f not in s.curled for s in ss) * 2 >= len(ss)) or touching

        def emit(name: str, samples: list[_S], margin: float, **kw: Any) -> None:
            score = float(np.mean([s.contact.score for s in samples if s.contact] or [0.0]))
            self._emit(name, track, samples, margin, object_track_id=obj_id, object_label=label,
                       contact_score=score, **kw)  # fmt: skip

        self._reach(track, run, emit)
        grasped = sum(s.grasping for s in ss) >= max(2, c["grasp_share"] * len(ss))
        if grasped:
            grasp_ss = [s for s in ss if s.grasping]
            head = [s for s in grasp_ss if s.t - grasp_ss[0].t <= c["grasp_s"]]
            curled = lambda s: float(sum(f in s.curled for f in FOUR))  # noqa: E731
            emit("grasp", head, _clip(np.mean([curled(s) for s in head]) / 4), fingers=touching,
                 measurements={"curled_fingers": [curled(s) for s in head]},
                 thresholds={"grasp_curled": c["grasp_curled"]},
                 rule=f"hand closes (≥ {c['grasp_curled']:g} fingers curled) while touching the object")  # fmt: skip
            if not video_end:
                tail = [s for s in ss if ss[-1].t - s.t <= c["grasp_s"]]
                emit("release", tail, 1.0, fingers=touching,
                     measurements={"contact_score": [s.contact.score if s.contact else 0.0 for s in tail]},
                     rule="a grasped object stops being touched")  # fmt: skip
            self._carry(ss, emit, touching)
        else:
            self._touch(ss, emit, working)
        self._depth(ss, emit, touching if grasped else working)
        self._manipulate(ss, emit, touching)

    def _reach(self, track: _Track, run: _Run, emit) -> None:
        c, start = self.c, run.samples[0]
        if start.obj is None:
            return
        box = box_px(start.obj.bbox, self.width, self.height)
        pre = [s for s in run.before if start.t - s.t <= c["reach_window_s"]] + [start]
        d = [min(distance_to_box(s.px[i, :2], box) for i in TIPS.values()) for s in pre]
        tol = 0.02 * start.size
        a = len(pre) - 1
        while a > 0 and d[a - 1] >= d[a] - tol:  # walk back while it was approaching (or level)…
            a -= 1
        while a < len(pre) - 1 and d[a + 1] >= d[a] - tol:  # …then drop the level stretch it started from
            a += 1
        closed = d[a] - d[-1]
        need = c["reach_distance"] * self.width
        if closed < need or len(pre) - a < 3:
            return
        ss = pre[a:]
        emit("reach", ss, _clip(closed / need - 1) * 0.5 + 0.5, fingers=(),
             measurements={"distance_to_object_px": d[a:]}, thresholds={"reach_distance_px": need},
             attributes={"closed_px": round(closed, 1)},
             rule=f"fingertips close ≥ {c['reach_distance']:g} frame widths on the object, then touch it")  # fmt: skip

    def _carry(self, ss: list[_S], emit, touching: tuple[str, ...]) -> None:
        c = self.c
        vel = [self._velocity(ss, i, self._center) for i in range(len(ss))]

        def label(i: int) -> str | None:
            vx, vy = float(vel[i][0]), float(vel[i][1])
            if vy <= -c["lift_speed"] * self.height:
                return "up"
            if vy >= c["lift_speed"] * self.height:
                return "down"
            if abs(vx) >= c["carry_speed"] * self.width and abs(vx) > abs(vy):
                return "side"
            obj_still = math.hypot(vx, vy) < c["still_speed"] * ss[i].size * 0.5
            if obj_still and ss[i].speed < c["still_speed"] * ss[i].size:
                return "still"
            return None

        for lab, group in self._phases(ss, label):
            centres = [self._center(s) for s in group]
            dy = float(centres[-1][1] - centres[0][1])
            dx = float(centres[-1][0] - centres[0][0])
            m = {
                "object_center_x_px": [float(p[0]) for p in centres],
                "object_center_y_px": [float(p[1]) for p in centres],
            }
            if lab in ("up", "down") and abs(dy) >= c["lift_distance"] * self.height:
                need = c["lift_distance"] * self.height
                emit("pick_up" if lab == "up" else "put_down", group, _clip(abs(dy) / need - 1) * 0.5 + 0.5,
                     fingers=touching, measurements=m, attributes={"lift_px": round(-dy, 1)},
                     thresholds={"lift_speed_px_s": c["lift_speed"] * self.height, "lift_distance_px": need},
                     rule=f"grasped object {'rises' if lab == 'up' else 'falls'} ≥ {c['lift_distance']:g} frame heights")  # fmt: skip
            elif lab == "side" and abs(dx) >= c["carry_distance"] * self.width:
                need = c["carry_distance"] * self.width
                emit("move", group, _clip(abs(dx) / need - 1) * 0.5 + 0.5, fingers=touching, measurements=m,
                     attributes={"direction": "right" if dx > 0 else "left", "distance_px": round(abs(dx), 1)},
                     thresholds={"carry_speed_px_s": c["carry_speed"] * self.width, "carry_distance_px": need},
                     rule=f"grasped object carried sideways ≥ {c['carry_distance']:g} frame widths")  # fmt: skip
            elif lab == "still" and self._duration(group) >= c["hold_min_s"]:
                emit("hold", group, _clip(self._duration(group) / c["hold_min_s"] - 1) * 0.5 + 0.5, fingers=touching,
                     measurements={"wrist_speed_px_s": [s.speed for s in group]},
                     thresholds={"hold_min_s": c["hold_min_s"]},
                     rule=f"object grasped and held still for ≥ {c['hold_min_s']:g} s")  # fmt: skip

    def _touch(self, ss: list[_S], emit, touching: tuple[str, ...]) -> None:
        c = self.c
        dur = self._duration(ss)
        fingers_in = [float(len(s.contact.fingers)) if s.contact else 0.0 for s in ss]
        if dur <= c["tap_max_s"]:
            emit("tap", ss, _clip(1 - dur / c["tap_max_s"]) * 0.5 + 0.5, fingers=touching,
                 measurements={"fingertips_on_object": fingers_in}, thresholds={"tap_max_s": c["tap_max_s"]},
                 attributes={"duration_s": round(dur, 3)},
                 rule=f"fingertip contact lasting ≤ {c['tap_max_s']:g} s")  # fmt: skip
            return
        hand_dx = float(ss[-1].wrist[0] - ss[0].wrist[0])
        obj_dx = float(self._center(ss[-1])[0] - self._center(ss[0])[0])
        if (
            abs(hand_dx) >= c["drag_distance"] * self.width
            and obj_dx * hand_dx > 0
            and abs(obj_dx) >= 0.5 * abs(hand_dx)
        ):
            emit("drag", ss, _clip(abs(obj_dx) / abs(hand_dx)), fingers=touching,
                 measurements={"wrist_x_px": [float(s.wrist[0]) for s in ss],
                               "object_center_x_px": [float(self._center(s)[0]) for s in ss]},
                 attributes={"direction": "right" if hand_dx > 0 else "left"},
                 thresholds={"drag_distance_px": c["drag_distance"] * self.width},
                 rule="fingertip slides the object sideways without grasping it")  # fmt: skip
            return

        def still(i: int) -> str | None:
            return "still" if ss[i].speed < c["still_speed"] * ss[i].size else None

        for _, group in self._phases(ss, still):
            if self._duration(group) >= c["press_min_s"]:
                emit("press", group, _clip(self._duration(group) / c["press_min_s"] - 1) * 0.5 + 0.5, fingers=touching,
                     measurements={"wrist_speed_px_s": [s.speed for s in group],
                                   "fingertips_on_object": [float(len(s.contact.fingers)) if s.contact else 0.0 for s in group]},
                     thresholds={"press_min_s": c["press_min_s"], "still_speed": c["still_speed"]},
                     rule=f"fingertip rests on the object, hand still for ≥ {c['press_min_s']:g} s")  # fmt: skip

    def _depth(self, ss: list[_S], emit, touching: tuple[str, ...]) -> None:
        c = self.c
        window = c["phase_window_s"]
        head = [s.size for s in ss if s.t - ss[0].t <= window]
        tail = [s.size for s in ss if ss[-1].t - s.t <= window]
        if len(ss) < 4 or not head or not tail:
            return
        ratio = float(np.median(tail) / np.median(head))
        grow = 1 + c["depth_change"]
        if ratio >= grow or ratio <= 1 / grow:
            name = "pull" if ratio >= grow else "push"
            change = ratio if ratio >= 1 else 1 / ratio
            emit(name, ss, _clip((change - 1) / c["depth_change"] - 1) * 0.5 + 0.5, fingers=touching,
                 measurements={"hand_size_px": [s.size for s in ss]}, attributes={"size_ratio": round(ratio, 3)},
                 thresholds={"depth_change": c["depth_change"]},
                 rule=f"hand {'grows' if name == 'pull' else 'shrinks'} by ≥ {c['depth_change']:.0%} while touching "
                      f"the object ({'toward' if name == 'pull' else 'away from'} the camera)")  # fmt: skip

    def _manipulate(self, ss: list[_S], emit, touching: tuple[str, ...]) -> None:
        c = self.c

        def working(i: int) -> str | None:
            s = ss[i]
            return (
                "work" if s.speed < c["still_speed"] * s.size and s.rel_tip >= c["manipulate_speed"] else None
            )

        for _, group in self._phases(ss, working):
            if self._duration(group) >= c["manipulate_min_s"]:
                emit("manipulate", group, _clip(float(np.mean([s.rel_tip for s in group])) / c["manipulate_speed"] - 1) * 0.5 + 0.5,
                     fingers=touching, measurements={"fingertip_speed_hand_sizes_s": [s.rel_tip for s in group]},
                     thresholds={"manipulate_speed": c["manipulate_speed"], "manipulate_min_s": c["manipulate_min_s"]},
                     rule="fingers move on the object while the wrist stays in place")  # fmt: skip

    # --- output ------------------------------------------------------------------------------------

    def _emit(self, name: str, track: _Track, ss: list[_S], margin: float, *, fingers: tuple[str, ...] = (),
              object_track_id: int | None = None, object_label: str | None = None, contact_score: float | None = None,
              measurements: dict[str, list[float]] | None = None, thresholds: dict[str, float] | None = None,
              rule: str = "", attributes: dict[str, Any] | None = None) -> None:  # fmt: skip
        if not ss:
            return
        conf = float(np.mean([s.conf for s in ss])) * (0.5 + 0.5 * _clip(margin))
        if contact_score is not None:
            conf *= contact_score
        (self._out if track.confirmed else track.pending).append(
            MovementDetection(
                name=name,
                hand_track_id=track.track_id,
                handedness=track.handedness,
                frames=[s.frame for s in ss],
                confidence=round(_clip(conf), 4),
                fingers=fingers,
                object_track_id=object_track_id,
                object_label=object_label,
                measurements={
                    k: [round(float(v), 4) for v in vals] for k, vals in (measurements or {}).items()
                },
                thresholds=thresholds or {},
                rule=rule,
                attributes=attributes or {},
            )  # fmt: skip
        )
