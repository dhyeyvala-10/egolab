"""
Hand–object contact, estimated per frame from 2-D geometry.

A fingertip touches an object when it lies inside the object's box, grown by a margin proportional to the
hand's size (fingertips rest on an object's edge, and boxes are loose). This is an estimate: a single camera
can't tell a fingertip on an object from one hovering in front of it, so contact events carry the object
detector's confidence, and reviewers confirm them (Phase 5).
"""

from dataclasses import dataclass

import numpy as np

from egolabs.cv.keypoints import FINGERS
from egolabs.cv.movement.base import Contact, HandState, ObjectState

TIPS = {name: joints[-1] for name, joints in FINGERS.items()}
WRIST, MIDDLE_MCP = 0, 9


@dataclass(frozen=True)
class ContactConfig:
    margin: float = 0.12  # hand sizes added around each side of the object's box
    min_fingers: int = 1


def to_px(keypoints: np.ndarray, width: int, height: int) -> np.ndarray:
    """21×3 normalised keypoints → pixels (z on x's scale, as the hand models output it)."""
    return keypoints.astype(np.float64) * np.array([width, height, width])


def hand_size(px: np.ndarray) -> float:
    """Wrist to middle-finger knuckle, in pixels: a scale for the hand that doesn't change with its pose."""
    return float(np.linalg.norm(px[MIDDLE_MCP, :2] - px[WRIST, :2]))


def box_px(
    bbox: tuple[float, float, float, float], width: int, height: int
) -> tuple[float, float, float, float]:
    x, y, w, h = bbox
    return x * width, y * height, (x + w) * width, (y + h) * height


def distance_to_box(point: np.ndarray, box: tuple[float, float, float, float]) -> float:
    """Pixels from a point to a box (x0, y0, x1, y1); 0 inside it."""
    dx = max(box[0] - point[0], 0.0, point[0] - box[2])
    dy = max(box[1] - point[1], 0.0, point[1] - box[3])
    return float((dx * dx + dy * dy) ** 0.5)


def find_contacts(
    hands: list[HandState],
    objects: list[ObjectState],
    width: int,
    height: int,
    config: ContactConfig | None = None,
) -> list[Contact]:
    config = config or ContactConfig()
    out = []
    for hand in hands:
        px = to_px(hand.keypoints, width, height)
        pad = config.margin * hand_size(px)
        for obj in objects:
            x0, y0, x1, y1 = box_px(obj.bbox, width, height)
            touching = tuple(
                name
                for name, i in TIPS.items()
                if x0 - pad <= px[i, 0] <= x1 + pad and y0 - pad <= px[i, 1] <= y1 + pad
            )
            if len(touching) >= config.min_fingers:
                score = min(1.0, obj.score * (0.6 + 0.4 * len(touching) / len(TIPS)))
                out.append(Contact(hand.track_id, obj.track_id, touching, score))
    return out
