"""
Persistent hand track IDs across frames, independent of the model.

Detections are matched to live tracks greedily by cost (box overlap, wrist distance, handedness). A track
survives up to `max_missed` processed frames without a detection (a *missing detection*); after that it
ends. A new track that starts soon after a same-handed track ended, close to where it was lost, is a
*tracking failure*: the same hand was dropped and picked up again under a new ID.
"""

from dataclasses import dataclass, field

import numpy as np

from egolabs.cv.adapters.base import HandDetection, HandResult


@dataclass(frozen=True)
class TrackerConfig:
    max_missed: int = 10  # processed frames a track may go undetected before it ends
    max_cost: float = 1.2  # detections costlier than this to a track start a new track
    handedness_penalty: float = 0.5
    reacquire_frames: int = 45  # a same-handed track starting within this many frames of a loss…
    reacquire_distance: float = 0.25  # …and this close (fraction of the frame) counts as a failure


@dataclass
class TrackedHand:
    track_id: int
    detection: HandDetection


@dataclass
class TrackFailure:
    frame: int  # first frame of the new track
    lost_track_id: int
    new_track_id: int
    handedness: str
    gap_frames: int


@dataclass
class _Track:
    track_id: int
    handedness: str
    bbox: tuple[float, float, float, float]
    wrist: np.ndarray
    first_frame: int
    last_frame: int
    missed: int = 0


@dataclass
class _Ended:
    track: _Track
    ended_at: int  # frame index of the last detection


@dataclass
class TrackerSummary:
    failures: list[TrackFailure] = field(default_factory=list)
    # frames inside a track's life where it had no detection: {track_id: count}
    missing: dict[int, int] = field(default_factory=dict)


def iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax0, ay0, aw, ah = a
    bx0, by0, bw, bh = b
    ix = max(0.0, min(ax0 + aw, bx0 + bw) - max(ax0, bx0))
    iy = max(0.0, min(ay0 + ah, by0 + bh) - max(ay0, by0))
    inter = ix * iy
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


class HandTracker:
    def __init__(self, config: TrackerConfig | None = None) -> None:
        self.config = config or TrackerConfig()
        self._live: list[_Track] = []
        self._ended: list[_Ended] = []
        self._next_id = 1
        self.summary = TrackerSummary()

    def _cost(self, track: _Track, det: HandDetection) -> float:
        wrist = det.keypoints[0, :2]
        distance = float(np.linalg.norm(wrist - track.wrist))
        cost = (1.0 - iou(track.bbox, det.bbox)) + distance
        if det.handedness != track.handedness:
            cost += self.config.handedness_penalty
        return cost

    def update(self, result: HandResult) -> list[TrackedHand]:
        frame = result.frame_index
        pairs = sorted(
            (
                (self._cost(t, d), ti, di)
                for ti, t in enumerate(self._live)
                for di, d in enumerate(result.hands)
            ),
            key=lambda p: p[0],
        )
        used_t: set[int] = set()
        used_d: set[int] = set()
        assigned: dict[int, int] = {}
        for cost, ti, di in pairs:
            if cost > self.config.max_cost or ti in used_t or di in used_d:
                continue
            used_t.add(ti)
            used_d.add(di)
            assigned[di] = ti

        out: list[TrackedHand] = []
        for di, det in enumerate(result.hands):
            if di in assigned:
                track = self._live[assigned[di]]
                if track.missed:
                    self.summary.missing[track.track_id] = (
                        self.summary.missing.get(track.track_id, 0) + track.missed
                    )
                track.bbox, track.wrist = det.bbox, det.keypoints[0, :2].copy()
                track.last_frame, track.missed = frame, 0
                # Handedness follows the latest confident detection.
                track.handedness = det.handedness
            else:
                track = _Track(
                    self._next_id, det.handedness, det.bbox, det.keypoints[0, :2].copy(), frame, frame
                )
                self._next_id += 1
                self._check_reacquire(track, frame)
                self._live.append(track)
            out.append(TrackedHand(track.track_id, det))

        survivors = []
        for ti, track in enumerate(self._live):
            if ti in used_t or track.last_frame == frame:
                survivors.append(track)
                continue
            track.missed += 1
            if track.missed > self.config.max_missed:
                self._ended.append(_Ended(track, track.last_frame))
            else:
                survivors.append(track)
        self._live = survivors
        return out

    def _check_reacquire(self, new: _Track, frame: int) -> None:
        cfg = self.config
        for ended in reversed(self._ended):
            gap = frame - ended.ended_at
            if gap > cfg.reacquire_frames + cfg.max_missed:
                break
            old = ended.track
            if (
                old.handedness == new.handedness
                and float(np.linalg.norm(old.wrist - new.wrist)) <= cfg.reacquire_distance
            ):
                self.summary.failures.append(
                    TrackFailure(frame, old.track_id, new.track_id, new.handedness, gap)
                )
                self._ended.remove(ended)
                return

    def finish(self) -> TrackerSummary:
        """End every live track (trailing misses are the video ending, not missing detections)."""
        self._live = []
        return self.summary
