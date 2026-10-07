"""
The spec's movement classes (Phase 4), as shipped. Migration 0005 inserts a frozen copy of this list; teams
edit labels, descriptions, and whether a class is active through the API, and add custom classes.

Each entry: (name, label, description, requires_object).
"""

BUILTIN: list[tuple[str, str, str, bool]] = [
    ("hand_enter", "Hand enters frame", "A hand comes into view.", False),
    ("hand_exit", "Hand exits frame", "A hand leaves the view.", False),
    ("reach", "Reach", "The hand moves toward an object it then touches.", True),
    ("grasp", "Grasp", "The hand closes on an object.", True),
    ("release", "Release", "The hand lets go of an object it was grasping.", True),
    ("pinch", "Pinch", "Thumb and index fingertips held together.", False),
    ("point", "Point", "Index finger extended with the other fingers curled.", False),
    ("tap", "Tap", "A fingertip touches an object briefly.", True),
    ("swipe", "Swipe", "A fast, straight sweep of the hand across the view.", False),
    ("rotate", "Rotate", "The hand turns about the camera axis.", False),
    ("push", "Push", "The hand moves away from the camera while touching an object.", True),
    ("pull", "Pull", "The hand moves toward the camera while touching an object.", True),
    ("pick_up", "Pick up", "An object is lifted with the hand grasping it.", True),
    ("put_down", "Put down", "A grasped object is lowered.", True),
    ("hold", "Hold", "An object is grasped and held still.", True),
    ("move", "Move", "A grasped object is carried sideways.", True),
    ("manipulate", "Manipulate", "Fingers work on an object while the hand stays in place.", True),
    ("press", "Press", "A fingertip rests on an object without grasping it.", True),
    ("drag", "Drag", "A fingertip slides an object along without grasping it.", True),
    (
        "gesture",
        "Gesture",
        "A static hand sign away from objects (e.g. victory, thumbs up, open palm).",
        False,
    ),
]


def rows() -> list[dict]:
    return [
        {"name": n, "label": label, "description": d, "builtin": True, "requires_object": o}
        for n, label, d, o in BUILTIN
    ]
