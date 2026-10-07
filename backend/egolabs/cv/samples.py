"""
Sample footage with known ground truth, for tests and `make seed`.

The photos are MediaPipe's own test images (Apache-2.0, fetched from the public `mediapipe-assets` bucket
and checked against pinned SHA-256s), several with published reference landmarks. A clip moves each photo
across the frame with a known scale, rotation, and offset per frame, so the correct keypoint position in
every frame is the reference landmark under that frame's transform — real hands, exact answers.

Scene clips (Phase 4) put a hand, cut out along its reference landmarks, over an object photo; both move on
known paths, so the object's box and the moment the fingertips reach it are known too.
"""

import math
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from egolabs.config import get_settings
from egolabs.cv.assets import ModelAsset, ensure

_BUCKET = "https://storage.googleapis.com/mediapipe-assets/"
PHOTOS: dict[str, ModelAsset] = {
    name: ModelAsset(name, _BUCKET + name, sha)
    for name, sha in {
        "pointing_up.jpg": "ecf8ca2611d08fa25948a4fc10710af9120e88243a54da6356bacea17ff3e36e",
        "pointing_up_landmarks.pbtxt": "6bfcd360c0caa82559396d387ac30e1d59efab3b3d96b5512f4f018d0abae7c4",
        "victory.jpg": "84cb8853e3df614e0cb5c93a25e3e2f38ea5e4f92fd428ee7d867ed3479d5764",
        "victory_landmarks.pbtxt": "73fb59741872bc66b79982d4c9765a4128d6308cc5d919100615080c0f4c0c55",
        "thumb_up.jpg": "5d673c081ab13b8a1812269ff57047066f9c33c07db5f4178089e8cb3fdc0291",
        "thumb_up_landmarks.pbtxt": "feddaa81e188b9bceae12a96766f71e8ff3b2b316b4a31d64054d8a329e6015e",
        "right_hands.jpg": "4b5134daa4cb60465535239535f9f74c2842aba3aa5fd30bf04ef5678f93d87f",
        "left_hands.jpg": "240c082e80128ff1ca8a83ce645e2ba4d8bc30f0967b7991cf5fa375bab489e1",
        "woman_hands.jpg": "70cbeb38e198c9862202e0979c21a99b40ca980d3e7b250176c85b1636a40f12",
        "fist.jpg": "43fa1cabf3f90d574accc9a56986e2ee48638ce59fc65af1846487f73bb2ef24",
        "fist_landmarks.pbtxt": "4b0ad2b00d5f2d140450f9f168af0f7422ecf6b630b7d64a213bcf6f04fb078b",
        "man-woman-okay.jpg": "064bbf589dc1a2e05dff7e3fdddd00bbe5c5feadf4fd350f0e515f5a6bbfbbc4",
        "burger_crop.jpg": "8f58de573f0bf59a49c3d86cfabb9ad4061481f574aa049177e8da3963dddc50",
    }.items()
}


def fetch(name: str) -> Path:
    return ensure(PHOTOS[name])


def reference_landmarks(photo: str) -> tuple[str, np.ndarray]:
    """(handedness, 21×2 normalised x, y) published for a test photo."""
    text = fetch(photo.replace(".jpg", "_landmarks.pbtxt")).read_text()
    label = re.search(r'label: "(\w+)"', text)
    points = re.findall(r"x: ([-\d.e]+)\s+y: ([-\d.e]+)", text)[:21]
    return (label.group(1).lower() if label else "unknown"), np.array(points, dtype=np.float64)


@dataclass(frozen=True)
class Placement:
    """Where a photo sits in a clip frame: canvas pixel = matrix · (photo pixel − crop origin, 1)."""

    matrix: tuple[tuple[float, float, float], tuple[float, float, float]]
    origin: tuple[float, float] = (0.0, 0.0)  # top left of the photo crop used

    def apply(self, px: np.ndarray) -> np.ndarray:
        m = np.asarray(self.matrix)
        p = np.asarray(px, dtype=np.float64) - np.asarray(self.origin)
        return p @ m[:, :2].T + m[:, 2]


def _affine(
    scale: float, angle_deg: float, photo_center: tuple[float, float], canvas_center: tuple[float, float]
):
    """Scale and rotate about the photo's centre, then put that centre at `canvas_center`."""
    a = math.radians(angle_deg)
    lin = scale * np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
    t = np.asarray(canvas_center) - lin @ np.asarray(photo_center)
    return np.hstack([lin, t[:, None]])


def _warp(img: np.ndarray, m: np.ndarray, size: tuple[int, int], border=(255, 255, 255)) -> np.ndarray:
    import cv2

    # warpAffine maps pixel centres: photo pixel x lands at m·(x + ½) − ½ in canvas pixel indices.
    idx = m.copy()
    idx[:, 2] += m[:, :2] @ np.array([0.5, 0.5]) - 0.5
    return cv2.warpAffine(img, idx, size, flags=cv2.INTER_LINEAR, borderValue=border)


@dataclass
class Segment:
    photo: str
    frames: int
    # Photo height as a fraction of the canvas height, and the photo centre's path (fractions of the
    # canvas), from start to end; the scale also breathes by ±`zoom`, and the photo turns from angle[0]
    # to angle[1] degrees (clockwise on screen).
    height: float = 0.7
    start: tuple[float, float] = (0.4, 0.5)
    end: tuple[float, float] = (0.6, 0.5)
    zoom: float = 0.1
    angle: tuple[float, float] = (0.0, 0.0)
    crop: tuple[int, int, int, int] | None = None  # x0, y0, x1, y1 of the photo to use


@dataclass
class SampleClip:
    path: Path
    width: int
    height: int
    fps: int
    # One entry per frame: (photo, placement), or None for an empty frame.
    frames: list[tuple[str, Placement] | None]

    def expected(self, frame: int, landmarks: np.ndarray, photo_size: tuple[int, int]) -> np.ndarray:
        """Reference landmarks (normalised to the photo) → normalised to this clip's frame `frame`."""
        entry = self.frames[frame]
        assert entry is not None
        _, place = entry
        w, h = photo_size
        return place.apply(landmarks * [w, h]) / [self.width, self.height]


def make_clip(
    dest: Path, segments: list[Segment | int], width: int = 640, height: int = 480, fps: int = 30
) -> SampleClip:
    """Render the segments (an int is that many empty frames) into an H.264 clip."""
    import cv2

    frames: list[tuple[str, Placement] | None] = []
    settings = get_settings()
    proc = subprocess.Popen(
        [settings.ffmpeg_bin, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}",
         "-r", str(fps), "-i", "-", "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", "-g", "30", str(dest)],
        stdin=subprocess.PIPE, stderr=subprocess.PIPE,
    )  # fmt: skip
    assert proc.stdin is not None
    blank = np.full((height, width, 3), 255, np.uint8)
    for seg in segments:
        if isinstance(seg, int):
            for _ in range(seg):
                proc.stdin.write(blank.tobytes())
                frames.append(None)
            continue
        img = cv2.cvtColor(cv2.imread(str(fetch(seg.photo))), cv2.COLOR_BGR2RGB)
        origin = (0.0, 0.0)
        if seg.crop:
            x0, y0, x1, y1 = seg.crop
            img, origin = np.ascontiguousarray(img[y0:y1, x0:x1]), (float(x0), float(y0))
        ph, pw = img.shape[:2]
        for i in range(seg.frames):
            u = i / max(1, seg.frames - 1)
            scale = seg.height * height / ph * (1 + seg.zoom * math.sin(2 * math.pi * u))
            cx = (seg.start[0] + (seg.end[0] - seg.start[0]) * u) * width
            cy = (seg.start[1] + (seg.end[1] - seg.start[1]) * u) * height
            angle = seg.angle[0] + (seg.angle[1] - seg.angle[0]) * u
            m = _affine(scale, angle, (pw / 2, ph / 2), (cx, cy))
            proc.stdin.write(_warp(img, m, (width, height)).tobytes())
            frames.append((seg.photo, Placement((tuple(m[0]), tuple(m[1])), origin)))
    proc.stdin.close()
    err = proc.stderr.read().decode() if proc.stderr else ""
    if proc.wait() != 0:
        raise RuntimeError(err)
    return SampleClip(dest, width, height, fps, frames)


def photo_size(photo: str) -> tuple[int, int]:
    import cv2

    h, w = cv2.imread(str(fetch(photo))).shape[:2]
    return w, h


# --- scenes: a hand over an object (Phase 4) -------------------------------------------------------


@dataclass(frozen=True)
class HandPose:
    """A hand photo cut out along its reference landmarks; `anchor` (a landmark) moves from start to end."""

    photo: str  # needs <photo>_landmarks.pbtxt
    start: tuple[float, float]  # canvas px of the anchor landmark
    end: tuple[float, float]
    scale: float = 0.6
    anchor: int = 8  # index fingertip


@dataclass(frozen=True)
class ObjectPose:
    photo: str
    start: tuple[float, float]  # canvas px of the object photo's centre
    end: tuple[float, float]
    width: float = 240.0  # px on the canvas


@dataclass(frozen=True)
class SceneSegment:
    frames: int
    hand: HandPose | None = None
    obj: ObjectPose | None = None


@dataclass
class SceneFrame:
    hand: tuple[str, Placement] | None
    object_box: tuple[float, float, float, float] | None  # x0, y0, x1, y1 canvas px


@dataclass
class SceneClip:
    path: Path
    width: int
    height: int
    fps: int
    frames: list[SceneFrame]

    def hand_landmarks(self, frame: int) -> np.ndarray | None:
        """Where the hand's reference landmarks are in `frame` (canvas px), if a hand is shown."""
        entry = self.frames[frame].hand
        if entry is None:
            return None
        photo, place = entry
        _, ref = reference_landmarks(photo)
        return place.apply(ref * photo_size(photo))


def _cutout_mask(photo: str, shape: tuple[int, int]) -> np.ndarray:
    """Soft mask of the hand and its forearm, from the photo's reference landmarks."""
    import cv2

    h, w = shape
    _, ref = reference_landmarks(photo)
    pts = ref * [w, h]
    down = pts[0] - pts[9]
    down = down / np.linalg.norm(down) * np.linalg.norm(pts[0] - pts[9]) * 2.2  # the forearm below the wrist
    hull = np.vstack([pts, pts[0] + down, pts[5] + down, pts[17] + down]).astype(np.int32)
    mask = np.zeros((h, w), np.uint8)
    cv2.fillConvexPoly(mask, cv2.convexHull(hull), 255)
    size = max(3, int(np.linalg.norm(pts[0] - pts[9]) * 0.15) | 1)
    mask = cv2.GaussianBlur(cv2.dilate(mask, np.ones((size, size), np.uint8)), (size, size), 0)
    return mask.astype(np.float64) / 255.0


def make_scene_clip(
    dest: Path, segments: list[SceneSegment], width: int = 640, height: int = 480, fps: int = 30
) -> SceneClip:
    """Render scene segments (object behind, hand in front) into an H.264 clip."""
    import cv2

    settings = get_settings()
    proc = subprocess.Popen(
        [settings.ffmpeg_bin, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}",
         "-r", str(fps), "-i", "-", "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", "-g", "30", str(dest)],
        stdin=subprocess.PIPE, stderr=subprocess.PIPE,
    )  # fmt: skip
    assert proc.stdin is not None
    photos: dict[str, np.ndarray] = {}
    masks: dict[str, np.ndarray] = {}

    def photo(name: str) -> np.ndarray:
        if name not in photos:
            photos[name] = cv2.cvtColor(cv2.imread(str(fetch(name))), cv2.COLOR_BGR2RGB)
        return photos[name]

    out: list[SceneFrame] = []
    for seg in segments:
        for i in range(seg.frames):
            u = i / max(1, seg.frames - 1)
            canvas = np.full((height, width, 3), 236, np.uint8)
            box = None
            if seg.obj:
                img = photo(seg.obj.photo)
                ph, pw = img.shape[:2]
                c = np.add(seg.obj.start, np.subtract(seg.obj.end, seg.obj.start) * u)
                scale = seg.obj.width / pw
                m = _affine(scale, 0.0, (pw / 2, ph / 2), (float(c[0]), float(c[1])))
                layer = _warp(img, m, (width, height), border=(0, 0, 0))
                cover = _warp(np.full((ph, pw), 255, np.uint8), m, (width, height), border=(0,)) > 127
                canvas[cover] = layer[cover]
                box = (
                    c[0] - pw * scale / 2,
                    c[1] - ph * scale / 2,
                    c[0] + pw * scale / 2,
                    c[1] + ph * scale / 2,
                )
            hand = None
            if seg.hand:
                hp = seg.hand
                img = photo(hp.photo)
                ph, pw = img.shape[:2]
                if hp.photo not in masks:
                    masks[hp.photo] = _cutout_mask(hp.photo, (ph, pw))
                _, ref = reference_landmarks(hp.photo)
                a = ref[hp.anchor] * [pw, ph]
                target = np.add(hp.start, np.subtract(hp.end, hp.start) * u)
                m = np.array(
                    [[hp.scale, 0, target[0] - a[0] * hp.scale], [0, hp.scale, target[1] - a[1] * hp.scale]]
                )
                layer = _warp(img, m, (width, height), border=(0, 0, 0)).astype(np.float64)
                alpha = (
                    _warp((masks[hp.photo] * 255).astype(np.uint8), m, (width, height), border=(0,))[
                        ..., None
                    ]
                    / 255.0
                )
                canvas = (canvas * (1 - alpha) + layer * alpha).astype(np.uint8)
                hand = (hp.photo, Placement((tuple(m[0]), tuple(m[1]))))
            proc.stdin.write(canvas.tobytes())
            out.append(SceneFrame(hand, box))
    proc.stdin.close()
    err = proc.stderr.read().decode() if proc.stderr else ""
    if proc.wait() != 0:
        raise RuntimeError(err)
    return SceneClip(dest, width, height, fps, out)


BURGER_WIDTH = 260.0


def press_and_tap_scene() -> list[SceneSegment]:
    """A pointing hand comes in from the right, reaches the burger, presses it, then taps it and leaves."""
    burger = ObjectPose("burger_crop.jpg", (170, 250), (170, 250), BURGER_WIDTH)
    on, near = (282.0, 200.0), (400.0, 190.0)

    def hand(start, end):
        return HandPose("pointing_up.jpg", start, end, scale=0.75)

    return [
        SceneSegment(15, obj=burger),
        SceneSegment(45, hand((600, 185), on), burger),  # reach
        SceneSegment(36, hand(on, on), burger),  # press
        SceneSegment(30, hand(on, near), burger),
        SceneSegment(15, hand(near, near), burger),  # pointing, away from the burger
        SceneSegment(3, hand(near, on), burger),  # tap
        SceneSegment(4, hand(on, on), burger),
        SceneSegment(3, hand(on, near), burger),
        SceneSegment(10, hand(near, near), burger),
        SceneSegment(40, hand(near, (780, 190)), burger),  # leaves
        SceneSegment(15, obj=burger),
    ]


def grasp_scene() -> list[SceneSegment]:
    """A fist reaches the burger, grasps and holds it, lifts it, carries it left, puts it down, and lets go."""
    b0, b1 = (200.0, 280.0), (200.0, 190.0)  # burger centre: resting, lifted
    b2, b3 = (100.0, 190.0), (100.0, 280.0)  # carried left, put down
    grip = np.array([112.0, -30.0])  # fist anchor relative to the burger centre: knuckles over its right edge

    def at(c):
        return tuple(np.add(c, grip))

    def fist(start, end):
        return HandPose("fist.jpg", start, end, scale=0.7)

    def burger(start, end):
        return ObjectPose("burger_crop.jpg", start, end, BURGER_WIDTH * 0.92)

    return [
        SceneSegment(15, obj=burger(b0, b0)),
        SceneSegment(40, fist((600, 250), at(b0)), burger(b0, b0)),  # reach
        SceneSegment(40, fist(at(b0), at(b0)), burger(b0, b0)),  # grasp, hold
        SceneSegment(30, fist(at(b0), at(b1)), burger(b0, b1)),  # pick up
        SceneSegment(15, fist(at(b1), at(b1)), burger(b1, b1)),
        SceneSegment(30, fist(at(b1), at(b2)), burger(b1, b2)),  # move left
        SceneSegment(30, fist(at(b2), at(b3)), burger(b2, b3)),  # put down
        SceneSegment(40, fist(at(b3), (560, 250)), burger(b3, b3)),  # release, move away
        SceneSegment(20, obj=burger(b3, b3)),
    ]


# Hand motions with no object: pinch (the OK sign), a fast swipe, and a quarter turn.
GESTURE_SEGMENTS: list[Segment | int] = [
    Segment(
        "man-woman-okay.jpg",
        45,
        height=0.55,
        start=(0.45, 0.5),
        end=(0.5, 0.5),
        zoom=0.0,
        crop=(338, 95, 468, 270),
    ),  # fmt: skip
    10,
    Segment("pointing_up.jpg", 20, height=0.6, start=(0.25, 0.5), end=(0.25, 0.5), zoom=0.0),
    Segment("pointing_up.jpg", 12, height=0.6, start=(0.25, 0.5), end=(0.8, 0.5), zoom=0.0),  # swipe right
    Segment("pointing_up.jpg", 20, height=0.6, start=(0.8, 0.5), end=(0.8, 0.5), zoom=0.0),
    10,
    Segment("pointing_up.jpg", 15, height=0.6, start=(0.5, 0.5), end=(0.5, 0.5), zoom=0.0),
    Segment("pointing_up.jpg", 30, height=0.6, start=(0.5, 0.5), end=(0.5, 0.5), zoom=0.0, angle=(0.0, 90.0)),
    Segment(
        "pointing_up.jpg", 15, height=0.6, start=(0.5, 0.5), end=(0.5, 0.5), zoom=0.0, angle=(90.0, 90.0)
    ),
]
