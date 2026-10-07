"""The 21-keypoint hand schema (MediaPipe / OpenPose hand layout) shared by every adapter's output."""

KEYPOINT_NAMES: tuple[str, ...] = (
    "wrist",
    "thumb_cmc", "thumb_mcp", "thumb_ip", "thumb_tip",
    "index_mcp", "index_pip", "index_dip", "index_tip",
    "middle_mcp", "middle_pip", "middle_dip", "middle_tip",
    "ring_mcp", "ring_pip", "ring_dip", "ring_tip",
    "pinky_mcp", "pinky_pip", "pinky_dip", "pinky_tip",
)  # fmt: skip

WRIST = 0

# Joints of each finger, from the base to the tip.
FINGERS: dict[str, tuple[int, int, int, int]] = {
    "thumb": (1, 2, 3, 4),
    "index": (5, 6, 7, 8),
    "middle": (9, 10, 11, 12),
    "ring": (13, 14, 15, 16),
    "pinky": (17, 18, 19, 20),
}

# Bones drawn for the skeleton overlay.
CONNECTIONS: tuple[tuple[int, int], ...] = (
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (0, 17), (17, 18), (18, 19), (19, 20),
)  # fmt: skip

# The palm outline (wrist and finger bases), used to estimate when a fingertip is hidden behind it.
PALM = (0, 1, 5, 9, 13, 17)

SCHEMA = {
    "name": "hand-21",
    "keypoints": list(KEYPOINT_NAMES),
    "fingers": {name: list(joints) for name, joints in FINGERS.items()},
    "connections": [list(c) for c in CONNECTIONS],
    "coordinates": "x, y normalised to the frame (0–1, origin top left); z relative depth, wrist = 0",
}
