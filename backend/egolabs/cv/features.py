"""
Per-hand and per-finger features, computed frame by frame for each track (so memory stays flat however long
the video is).

Units: positions are stored normalised to the frame; speeds and accelerations are in source-video pixels per
second (per second²) so they read the same whatever resolution inference ran at. Directions and
orientations are image angles in degrees: 0° = right, 90° = down.

Visibility and occlusion are estimated from the keypoints (the hand models used here give no per-joint
visibility): a joint outside the frame is not visible, and a fingertip that projects inside the palm while
lying farther from the camera than the palm is flagged occluded.
"""

import math
from dataclasses import dataclass, field

import numpy as np

from egolabs.cv.adapters.base import HandDetection
from egolabs.cv.keypoints import FINGERS, PALM, WRIST
from egolabs.cv.smoothing import OneEuroConfig, OneEuroFilter

FINGER_NAMES = tuple(FINGERS)


def _inside(point: np.ndarray, polygon: np.ndarray) -> bool:
    """Ray-casting point-in-polygon test (2-D)."""
    x, y = point
    inside = False
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-12) + x1:
            inside = not inside
    return inside


def angle_deg(v: np.ndarray) -> float:
    return math.degrees(math.atan2(float(v[1]), float(v[0]))) % 360.0


@dataclass
class _Motion:
    """Backward-difference velocity and acceleration of one point."""

    pos: np.ndarray | None = None
    vel: np.ndarray = field(default_factory=lambda: np.zeros(2))
    t: float | None = None

    def step(self, pos: np.ndarray, t: float) -> tuple[np.ndarray, float]:
        if self.pos is None or self.t is None or t <= self.t:
            self.pos, self.t = pos.copy(), t
            return np.zeros(2), 0.0
        dt = t - self.t
        vel = (pos - self.pos) / dt
        accel = float(np.linalg.norm((vel - self.vel) / dt))
        self.pos, self.vel, self.t = pos.copy(), vel, t
        return vel, accel


@dataclass
class HandRow:
    frame: int
    timestamp_s: float
    track_id: int
    handedness: str
    handedness_score: float
    confidence: float
    bbox: tuple[float, float, float, float]
    keypoints: np.ndarray  # 21×3 smoothed, normalised
    raw_keypoints: np.ndarray  # 21×3 as the model output them
    wrist_velocity: np.ndarray  # px/s
    wrist_speed: float
    wrist_accel: float
    direction_deg: float
    displacement_px: float
    path_length_px: float


@dataclass
class FingerRow:
    frame: int
    timestamp_s: float
    track_id: int
    handedness: str
    finger: str
    joints: np.ndarray  # 4×2 normalised, base → tip
    orientation_deg: float
    tip_velocity: np.ndarray
    tip_speed: float
    tip_accel: float
    visibility: float
    occluded: bool
    confidence: float


class TrackFeatures:
    """Smoothing, kinematics, and finger features for one track."""

    def __init__(
        self, track_id: int, width: int, height: int, smoothing: OneEuroConfig | None = None
    ) -> None:
        self.track_id = track_id
        self.scale = np.array([width, height, width], dtype=np.float64)  # z is on the same scale as x
        self.filter = OneEuroFilter(smoothing)
        self.wrist = _Motion()
        self.tips = {name: _Motion() for name in FINGER_NAMES}
        self.start: np.ndarray | None = None
        self.last: np.ndarray | None = None
        self.path = 0.0

    def step(self, frame: int, t: float, det: HandDetection) -> tuple[HandRow, list[FingerRow]]:
        raw = det.keypoints.astype(np.float64)
        px = self.filter(raw * self.scale, t)  # smooth in pixels
        kp = px / self.scale
        wrist_px = px[WRIST, :2]
        if self.start is None:
            self.start = wrist_px.copy()
        if self.last is not None:
            self.path += float(np.linalg.norm(wrist_px - self.last))
        self.last = wrist_px.copy()
        vel, accel = self.wrist.step(wrist_px, t)
        speed = float(np.linalg.norm(vel))
        xy = np.clip(kp[:, :2], 0, 1)
        bbox = (float(xy[:, 0].min()), float(xy[:, 1].min()),
                float(xy[:, 0].max() - xy[:, 0].min()), float(xy[:, 1].max() - xy[:, 1].min()))  # fmt: skip
        hand = HandRow(
            frame=frame, timestamp_s=t, track_id=self.track_id, handedness=det.handedness,
            handedness_score=det.handedness_score, confidence=det.confidence, bbox=bbox,
            keypoints=kp.astype(np.float32), raw_keypoints=raw.astype(np.float32),
            wrist_velocity=vel, wrist_speed=speed, wrist_accel=accel,
            direction_deg=angle_deg(vel) if speed > 0 else 0.0,
            displacement_px=float(np.linalg.norm(wrist_px - self.start)), path_length_px=self.path,
        )  # fmt: skip

        palm_xy = px[list(PALM), :2]
        palm_z = float(px[list(PALM), 2].mean())
        fingers = []
        for name, joints in FINGERS.items():
            j = list(joints)
            pts = kp[j, :2]
            tip_px = px[j[-1], :2]
            tvel, taccel = self.tips[name].step(tip_px, t)
            in_frame = ((pts >= 0) & (pts <= 1)).all(axis=1)
            # Thumb joints sit on the palm outline, so only the other fingertips can hide behind it.
            occluded = name != "thumb" and _inside(tip_px, palm_xy) and float(px[j[-1], 2]) > palm_z
            conf = (
                float(det.keypoint_confidence[j].mean())
                if det.keypoint_confidence is not None
                else det.confidence
            )
            fingers.append(
                FingerRow(
                    frame=frame,
                    timestamp_s=t,
                    track_id=self.track_id,
                    handedness=det.handedness,
                    finger=name,
                    joints=pts.astype(np.float32),
                    orientation_deg=angle_deg(px[j[-1], :2] - px[j[0], :2]),
                    tip_velocity=tvel,
                    tip_speed=float(np.linalg.norm(tvel)),
                    tip_accel=taccel,
                    visibility=float(in_frame.mean()),
                    occluded=bool(occluded),
                    confidence=conf,
                )  # fmt: skip
            )
        return hand, fingers
