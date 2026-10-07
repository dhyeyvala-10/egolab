"""
Per-frame model output as Parquet in the derived bucket (never millions of keypoint rows in Postgres):
hand and finger rows for hand-tracking runs, object boxes for object-detection runs.

Files are split every `CHUNK_FRAMES` frames — `cv/<video>/<run>/hands/part-00000.parquet` holds frames
0–1799 — so a viewer or an export reads only the chunks it needs. Every row carries the video, run, and
model version it came from (principles 1 and 8).
"""

import io
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from egolabs import storage
from egolabs.config import get_settings
from egolabs.cv.features import FingerRow, HandRow

CHUNK_FRAMES = 1800

_f32 = pa.float32()
_list21 = pa.list_(_f32, 21)
_list4 = pa.list_(_f32, 4)
_ids = [("video_id", pa.string()), ("run_id", pa.string()), ("model_version_id", pa.string())]

HANDS_SCHEMA = pa.schema(
    [
        ("frame", pa.int32()), ("timestamp_s", pa.float64()), ("track_id", pa.int32()),
        ("handedness", pa.string()), ("handedness_score", _f32), ("confidence", _f32),
        ("bbox_x", _f32), ("bbox_y", _f32), ("bbox_w", _f32), ("bbox_h", _f32),
        ("wrist_x", _f32), ("wrist_y", _f32),
        ("kp_x", _list21), ("kp_y", _list21), ("kp_z", _list21),
        ("raw_kp_x", _list21), ("raw_kp_y", _list21), ("raw_kp_z", _list21),
        ("wrist_vx_px_s", _f32), ("wrist_vy_px_s", _f32), ("wrist_speed_px_s", _f32), ("wrist_accel_px_s2", _f32),
        ("direction_deg", _f32), ("displacement_px", _f32), ("path_length_px", _f32),
        *_ids,
    ]
)  # fmt: skip

FINGERS_SCHEMA = pa.schema(
    [
        ("frame", pa.int32()), ("timestamp_s", pa.float64()), ("track_id", pa.int32()),
        ("handedness", pa.string()), ("finger", pa.string()),
        ("tip_x", _f32), ("tip_y", _f32), ("joints_x", _list4), ("joints_y", _list4),
        ("orientation_deg", _f32), ("tip_vx_px_s", _f32), ("tip_vy_px_s", _f32), ("tip_speed_px_s", _f32),
        ("tip_accel_px_s2", _f32), ("visibility", _f32), ("occluded", pa.bool_()), ("confidence", _f32),
        *_ids,
    ]
)  # fmt: skip


OBJECTS_SCHEMA = pa.schema(
    [
        ("frame", pa.int32()), ("timestamp_s", pa.float64()), ("track_id", pa.int32()),
        ("label", pa.string()), ("score", _f32),
        ("bbox_x", _f32), ("bbox_y", _f32), ("bbox_w", _f32), ("bbox_h", _f32),
        *_ids,
    ]
)  # fmt: skip

SCHEMAS = {"hands": HANDS_SCHEMA, "fingers": FINGERS_SCHEMA, "objects": OBJECTS_SCHEMA}


def prefix(video_id: str, run_id: str) -> str:
    return f"cv/{video_id}/{run_id}"


def chunk_of(frame: int) -> int:
    return frame // CHUNK_FRAMES


class _Writer:
    """Uploads one Parquet part per chunk of frames and remembers the keys (the run's `output`)."""

    tables: tuple[str, ...] = ()

    def __init__(self, video_id: str, run_id: str, model_version_id: str) -> None:
        self.ids = {"video_id": video_id, "run_id": run_id, "model_version_id": model_version_id}
        self.prefix = prefix(video_id, run_id)
        self.chunk: int | None = None
        self.keys: dict[str, list[str]] = {t: [] for t in self.tables}
        self.rows = dict.fromkeys(self.tables, 0)

    def _upload(self, table: pa.Table, kind: str) -> None:
        assert self.chunk is not None
        buf = io.BytesIO()
        pq.write_table(table, buf, compression="zstd")
        key = f"{self.prefix}/{kind}/part-{self.chunk:05d}.parquet"
        storage.put_bytes(
            buf.getvalue(), get_settings().s3_bucket_derived, key, "application/vnd.apache.parquet"
        )
        self.keys[kind].append(key)
        self.rows[kind] += table.num_rows

    def flush(self) -> None:
        raise NotImplementedError

    def close(self) -> dict[str, Any]:
        self.flush()
        return {"prefix": self.prefix, "chunk_frames": CHUNK_FRAMES, **self.keys, "rows": self.rows}


class ChunkWriter(_Writer):
    """Hand and finger rows, buffered per chunk of frames and uploaded when the frames move past it."""

    tables = ("hands", "fingers")

    def __init__(self, video_id: str, run_id: str, model_version_id: str) -> None:
        super().__init__(video_id, run_id, model_version_id)
        self.hands: list[HandRow] = []
        self.fingers: list[FingerRow] = []

    def add(self, frame: int, hands: list[HandRow], fingers: list[FingerRow]) -> None:
        c = chunk_of(frame)
        if self.chunk is not None and c != self.chunk:
            self.flush()
        self.chunk = c
        self.hands += hands
        self.fingers += fingers

    def flush(self) -> None:
        if self.chunk is None or (not self.hands and not self.fingers):
            self.hands, self.fingers = [], []
            return
        n = len(self.hands)
        h = self.hands
        cols: dict[str, Any] = {
            "frame": [r.frame for r in h], "timestamp_s": [r.timestamp_s for r in h],
            "track_id": [r.track_id for r in h], "handedness": [r.handedness for r in h],
            "handedness_score": [r.handedness_score for r in h], "confidence": [r.confidence for r in h],
            "bbox_x": [r.bbox[0] for r in h], "bbox_y": [r.bbox[1] for r in h],
            "bbox_w": [r.bbox[2] for r in h], "bbox_h": [r.bbox[3] for r in h],
            "wrist_x": [float(r.keypoints[0, 0]) for r in h], "wrist_y": [float(r.keypoints[0, 1]) for r in h],
            "kp_x": [r.keypoints[:, 0].tolist() for r in h], "kp_y": [r.keypoints[:, 1].tolist() for r in h],
            "kp_z": [r.keypoints[:, 2].tolist() for r in h],
            "raw_kp_x": [r.raw_keypoints[:, 0].tolist() for r in h],
            "raw_kp_y": [r.raw_keypoints[:, 1].tolist() for r in h],
            "raw_kp_z": [r.raw_keypoints[:, 2].tolist() for r in h],
            "wrist_vx_px_s": [float(r.wrist_velocity[0]) for r in h],
            "wrist_vy_px_s": [float(r.wrist_velocity[1]) for r in h],
            "wrist_speed_px_s": [r.wrist_speed for r in h], "wrist_accel_px_s2": [r.wrist_accel for r in h],
            "direction_deg": [r.direction_deg for r in h], "displacement_px": [r.displacement_px for r in h],
            "path_length_px": [r.path_length_px for r in h],
        }  # fmt: skip
        cols.update({k: [v] * n for k, v in self.ids.items()})
        self._upload(pa.table(cols, schema=HANDS_SCHEMA), "hands")
        f = self.fingers
        m = len(f)
        fcols: dict[str, Any] = {
            "frame": [r.frame for r in f], "timestamp_s": [r.timestamp_s for r in f],
            "track_id": [r.track_id for r in f], "handedness": [r.handedness for r in f],
            "finger": [r.finger for r in f],
            "tip_x": [float(r.joints[-1, 0]) for r in f], "tip_y": [float(r.joints[-1, 1]) for r in f],
            "joints_x": [r.joints[:, 0].tolist() for r in f], "joints_y": [r.joints[:, 1].tolist() for r in f],
            "orientation_deg": [r.orientation_deg for r in f],
            "tip_vx_px_s": [float(r.tip_velocity[0]) for r in f], "tip_vy_px_s": [float(r.tip_velocity[1]) for r in f],
            "tip_speed_px_s": [r.tip_speed for r in f], "tip_accel_px_s2": [r.tip_accel for r in f],
            "visibility": [r.visibility for r in f], "occluded": [r.occluded for r in f],
            "confidence": [r.confidence for r in f],
        }  # fmt: skip
        fcols.update({k: [v] * m for k, v in self.ids.items()})
        self._upload(pa.table(fcols, schema=FINGERS_SCHEMA), "fingers")
        self.hands, self.fingers = [], []


@dataclass
class ObjectRow:
    frame: int
    timestamp_s: float
    track_id: int
    label: str
    score: float
    bbox: tuple[float, float, float, float]


class ObjectChunkWriter(_Writer):
    """Tracked object boxes, one Parquet part per chunk of frames."""

    tables = ("objects",)

    def __init__(self, video_id: str, run_id: str, model_version_id: str) -> None:
        super().__init__(video_id, run_id, model_version_id)
        self.objects: list[ObjectRow] = []

    def add(self, frame: int, objects: list[ObjectRow]) -> None:
        c = chunk_of(frame)
        if self.chunk is not None and c != self.chunk:
            self.flush()
        self.chunk = c
        self.objects += objects

    def flush(self) -> None:
        if self.chunk is None or not self.objects:
            self.objects = []
            return
        o = self.objects
        cols: dict[str, Any] = {
            "frame": [r.frame for r in o], "timestamp_s": [r.timestamp_s for r in o],
            "track_id": [r.track_id for r in o], "label": [r.label for r in o], "score": [r.score for r in o],
            "bbox_x": [r.bbox[0] for r in o], "bbox_y": [r.bbox[1] for r in o],
            "bbox_w": [r.bbox[2] for r in o], "bbox_h": [r.bbox[3] for r in o],
        }  # fmt: skip
        cols.update({k: [v] * len(o) for k, v in self.ids.items()})
        self._upload(pa.table(cols, schema=OBJECTS_SCHEMA), "objects")
        self.objects = []


# --- reading ---------------------------------------------------------------------------------------

_cache: "OrderedDict[str, pa.Table]" = OrderedDict()
_cache_lock = threading.Lock()
_CACHE_ITEMS = 64  # parts are immutable once written, so caching them is safe


def read_part(key: str) -> pa.Table:
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    table = pq.read_table(io.BytesIO(storage.get_bytes(get_settings().s3_bucket_derived, key)))
    with _cache_lock:
        _cache[key] = table
        while len(_cache) > _CACHE_ITEMS:
            _cache.popitem(last=False)
    return table


def read_window(
    output: dict[str, Any], kind: str, frame_from: int, frame_to: int, columns: list[str] | None = None
) -> pa.Table:
    """Rows for frames [frame_from, frame_to] from a run's `output`, reading only the chunks that overlap."""
    size = int(output.get("chunk_frames", CHUNK_FRAMES))
    wanted = set(range(frame_from // size, frame_to // size + 1))
    tables = []
    schema = SCHEMAS[kind]
    for key in output.get(kind, []):
        if int(key.rsplit("part-", 1)[1].split(".")[0]) not in wanted:
            continue
        t = read_part(key)
        mask = pc.and_(pc.greater_equal(t["frame"], frame_from), pc.less_equal(t["frame"], frame_to))
        t = t.filter(mask)
        tables.append(t.select(columns) if columns else t)
    if not tables:
        return (schema if not columns else pa.schema([schema.field(c) for c in columns])).empty_table()
    return pa.concat_tables(tables)
