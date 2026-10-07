"""
Synthetic hands for rule tests: a 2-D kinematic hand (hand-21 layout) posed by joint flexion, placed in a
frame by centre, size, and roll. Exact geometry, so each rule's inputs are known.
"""

import math

import numpy as np

from egolabs.cv.movement.base import Contact, HandState, MotionFrame, ObjectState
from egolabs.cv.movement.contact import find_contacts

W, H, FPS = 640, 480, 30.0

# Finger bases (MCP; thumb CMC) in hand sizes, hand pointing up (−y), wrist at the origin; segment lengths.
_BASES = {"thumb": (-0.3, -0.25), "index": (-0.25, -0.95), "middle": (0.0, -1.0), "ring": (0.22, -0.95),
          "pinky": (0.42, -0.85)}  # fmt: skip
_SEGMENTS = {"thumb": (0.35, 0.3, 0.28), "index": (0.45, 0.28, 0.22), "middle": (0.5, 0.3, 0.24),
             "ring": (0.45, 0.28, 0.22), "pinky": (0.35, 0.22, 0.2)}  # fmt: skip
_START = {"thumb": 1, "index": 5, "middle": 9, "ring": 13, "pinky": 17}
CURL = 100.0

POSES: dict[str, dict[str, float]] = {  # flexion per joint (degrees); thumb: negative angles tuck it in
    "open": {"thumb": 0, "index": 0, "middle": 0, "ring": 0, "pinky": 0},
    "point": {"thumb": 60, "index": 0, "middle": CURL, "ring": CURL, "pinky": CURL},
    "victory": {"thumb": 60, "index": 0, "middle": 0, "ring": CURL, "pinky": CURL},
    "thumbs_up": {"thumb": 0, "index": CURL, "middle": CURL, "ring": CURL, "pinky": CURL},
    "fist": {"thumb": 60, "index": CURL, "middle": CURL, "ring": CURL, "pinky": CURL},
    "relaxed": {"thumb": 25, "index": 35, "middle": 35, "ring": 35, "pinky": 35},
}


def _rot(v: np.ndarray, deg: float) -> np.ndarray:
    a = math.radians(deg)
    return np.array([v[0] * math.cos(a) - v[1] * math.sin(a), v[0] * math.sin(a) + v[1] * math.cos(a)])


def local_hand(pose: str) -> np.ndarray:
    """21×2 in hand sizes, pointing up."""
    flex = POSES[pose] if pose != "pinch" else POSES["open"] | {"index": 45}
    pts = np.zeros((21, 2))
    for name, base in _BASES.items():
        b = np.array(base)
        if name == "thumb":
            direction = (
                np.array([0.0, -1.0])
                if pose == "thumbs_up"
                else np.array([-0.7, -0.7]) / math.hypot(0.7, 0.7)
            )
            sign = 1.0  # thumb flexes toward the palm (clockwise)
        else:
            direction = b / np.linalg.norm(b)
            sign = 1.0
        pts[_START[name]] = b
        cur, d = b, direction
        for k, length in enumerate(_SEGMENTS[name]):
            d = _rot(d, sign * flex[name] * (0.8 if k == 0 and name != "thumb" else 1.0))
            cur = cur + d * length
            pts[_START[name] + k + 1] = cur
    if pose == "pinch":  # bring the thumb tip onto the index tip along a straight thumb
        tip = pts[8] + np.array([0.04, 0.02])
        base = pts[1]
        for k in (1, 2, 3):
            pts[1 + k] = base + (tip - base) * (k / 3)
    return pts


def place(pose: str, center: tuple[float, float], size: float = 80.0, roll: float = -90.0) -> np.ndarray:
    """21×3 normalised keypoints: hand-local points scaled by `size` px, rotated so wrist→middle points at
    `roll` degrees (image coordinates, −90 = up), wrist at `center` px."""
    local = local_hand(pose) * size
    turned = np.array([_rot(p, roll + 90.0) for p in local]) + np.array(center)
    out = np.zeros((21, 3))
    out[:, 0], out[:, 1] = turned[:, 0] / W, turned[:, 1] / H
    return out


def frames(
    poses: list[tuple[str, tuple[float, float], float, float] | None],
    objects: list[list[ObjectState]] | None = None,
    confidence: float = 0.95,
    tip_speed: list[dict[str, float]] | None = None,
) -> list[MotionFrame]:
    """One MotionFrame per entry: (pose, wrist centre px, size px, roll) for hand track 1, or None for no hand."""
    out = []
    prev: tuple[np.ndarray, float] | None = None
    prev_tips: np.ndarray | None = None
    for i, entry in enumerate(poses):
        t = i / FPS
        objs = objects[i] if objects else []
        if entry is None:
            out.append(MotionFrame(i, t, [], objs, []))
            prev = None
            prev_tips = None
            continue
        pose, center, size, roll = entry
        kp = place(pose, center, size, roll)
        wrist = np.array(center, dtype=float)
        tips = kp[[4, 8, 12, 16, 20], :2] * [W, H]
        v = (wrist - prev[0]) / (t - prev[1]) if prev else np.zeros(2)
        speeds = (
            {f: float(s) for f, s in zip(("thumb", "index", "middle", "ring", "pinky"),
                                          np.linalg.norm(tips - prev_tips, axis=1) * FPS, strict=True)}
            if prev_tips is not None else dict.fromkeys(("thumb", "index", "middle", "ring", "pinky"), 0.0)
        )  # fmt: skip
        if tip_speed:
            speeds = tip_speed[i]
        prev, prev_tips = (wrist, t), tips
        hand = HandState(1, "right", confidence, kp, (float(v[0]), float(v[1])), speeds)
        contacts: list[Contact] = find_contacts([hand], objs, W, H)
        out.append(MotionFrame(i, t, [hand], objs, contacts))
    return out


def box(
    cx: float, cy: float, w: float, h: float, track_id: int = 1, label: str = "cup", score: float = 0.9
) -> ObjectState:
    """An object box centred at (cx, cy) px, w × h px."""
    return ObjectState(track_id, label, score, ((cx - w / 2) / W, (cy - h / 2) / H, w / W, h / H))
