"""
Persistent object track IDs across frames, independent of the detector.

Detections are matched to live tracks of the same label greedily by box overlap (falling back to centre
distance for fast or small objects). A track survives `max_missed` processed frames without a detection —
objects are often hidden by the hand holding them — then ends; a later detection starts a new track.
"""

from dataclasses import dataclass, field

from egolabs.cv.adapters.base import ObjectDetection, ObjectResult
from egolabs.cv.tracking import iou


@dataclass(frozen=True)
class ObjectTrackerConfig:
    max_missed: int = 15  # processed frames a track may go undetected (e.g. occluded by the hand)
    min_iou: float = 0.2
    max_center_distance: float = 0.15  # fraction of the frame, when boxes don't overlap enough


@dataclass
class TrackedObject:
    track_id: int
    detection: ObjectDetection


@dataclass
class _Track:
    track_id: int
    label: str
    bbox: tuple[float, float, float, float]
    last_frame: int
    missed: int = 0


@dataclass
class ObjectTrackerSummary:
    missing: dict[int, int] = field(default_factory=dict)  # frames inside a track's life with no detection


def _center(b: tuple[float, float, float, float]) -> tuple[float, float]:
    return b[0] + b[2] / 2, b[1] + b[3] / 2


class ObjectTracker:
    def __init__(self, config: ObjectTrackerConfig | None = None) -> None:
        self.config = config or ObjectTrackerConfig()
        self._live: list[_Track] = []
        self._next_id = 1
        self._missing: dict[int, int] = {}

    def _cost(self, track: _Track, det: ObjectDetection) -> float | None:
        if track.label != det.label:
            return None
        overlap = iou(track.bbox, det.bbox)
        if overlap >= self.config.min_iou:
            return 1.0 - overlap
        (tx, ty), (dx, dy) = _center(track.bbox), _center(det.bbox)
        dist = ((tx - dx) ** 2 + (ty - dy) ** 2) ** 0.5
        return 1.0 + dist if dist <= self.config.max_center_distance else None

    def update(self, result: ObjectResult) -> list[TrackedObject]:
        pairs = []
        for ti, track in enumerate(self._live):
            for di, det in enumerate(result.objects):
                cost = self._cost(track, det)
                if cost is not None:
                    pairs.append((cost, ti, di))
        pairs.sort()
        used_t: set[int] = set()
        used_d: set[int] = set()
        out: list[TrackedObject] = []
        for _, ti, di in pairs:
            if ti in used_t or di in used_d:
                continue
            used_t.add(ti)
            used_d.add(di)
            track, det = self._live[ti], result.objects[di]
            if track.missed:  # seen again: the frames it went unseen were missing detections
                self._missing[track.track_id] = self._missing.get(track.track_id, 0) + track.missed
            track.bbox, track.last_frame, track.missed = det.bbox, result.frame_index, 0
            out.append(TrackedObject(track.track_id, det))
        survivors = []
        for ti, track in enumerate(self._live):
            if ti in used_t:
                survivors.append(track)
                continue
            track.missed += 1
            if track.missed <= self.config.max_missed:
                survivors.append(track)
        self._live = survivors
        for di, det in enumerate(result.objects):
            if di not in used_d:
                track = _Track(self._next_id, det.label, det.bbox, result.frame_index)
                self._next_id += 1
                self._live.append(track)
                out.append(TrackedObject(track.track_id, det))
        return sorted(out, key=lambda t: t.track_id)

    def finish(self) -> ObjectTrackerSummary:
        """End every live track (trailing misses are the video ending, not missing detections)."""
        self._live = []
        return ObjectTrackerSummary(missing=dict(self._missing))
