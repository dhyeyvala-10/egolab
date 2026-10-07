"""
Exporting a dataset version (spec Phase 6). Each export is one zip in the derived bucket, and every format
carries `manifest.json`: the dataset, the version's content hash, spec, pinned inputs, counts, the model
versions behind it, the class taxonomy, and the keypoint schema, so a file on disk can be traced back.

- `jsonl`: `samples.jsonl`, one sample per line (label, frames, times, hand, object, review state, the model
  versions and runs, the raw video's sha256 and storage key) with its per-frame hand keypoints and object box.
- `parquet`: `samples.parquet`, `keypoints.parquet` (one row per sample frame: 21 keypoints), and
  `objects.parquet` (the sample's object box per frame).
- `coco`: `annotations/{train,val,test}.json` in COCO keypoint format, one image per sample (its key frame,
  decoded from the raw video, in `images/`): the hand's 21 keypoints and box, the movement class as the
  category, and the event (frames, object box, review state) in `attributes`.
- `webdataset`: `{split}-{shard}.tar` shards; per sample `<key>.json` (the sample), `<key>.jpg` (its key
  frame), and `<key>.keypoints.json` (its per-frame keypoints).
- `egolabs` (native): `samples.parquet`, `keypoints.parquet`, `objects.parquet`, `evidence.jsonl` (the frames
  and measurements that produced each prediction), `videos.json` (raw-file provenance, ffprobe metadata,
  session, device, operator), `splits/{train,val,test}.txt`, and the manifest.

A sample's key frame is its hand track's frame nearest the middle of the sample.
"""

import io
import json
import re
import subprocess
import tarfile
import tempfile
import uuid
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import select
from sqlalchemy.orm import Session

from egolabs import storage
from egolabs.config import get_settings
from egolabs.cv import frames as frames_mod
from egolabs.cv import keypoints, store
from egolabs.datasets.build import SPLITS, samples_of
from egolabs.events import record_event
from egolabs.ingest.media import input_args
from egolabs.models import (
    BuildStatus,
    CaptureSession,
    CvRun,
    Dataset,
    DatasetExport,
    DatasetVersion,
    DatasetVersionSample,
    Device,
    ExportFormat,
    LineageEdge,
    ModelVersion,
    MovementClass,
    MovementEvent,
    Operator,
    Video,
)
from egolabs.worker.runtime import JobContext, job_handler

IMAGE_FORMATS = {ExportFormat.coco, ExportFormat.webdataset}
_f32 = pa.float32()
KEYPOINT_SCHEMA = pa.schema([
    ("sample_id", pa.string()), ("sample_no", pa.int32()), ("frame", pa.int32()), ("timestamp_s", pa.float64()),
    ("handedness", pa.string()), ("confidence", _f32), ("bbox_x", _f32), ("bbox_y", _f32), ("bbox_w", _f32),
    ("bbox_h", _f32), ("kp_x", pa.list_(_f32, 21)), ("kp_y", pa.list_(_f32, 21)), ("kp_z", pa.list_(_f32, 21)),
])  # fmt: skip
OBJECT_SCHEMA = pa.schema([
    ("sample_id", pa.string()), ("sample_no", pa.int32()), ("frame", pa.int32()), ("timestamp_s", pa.float64()),
    ("label", pa.string()), ("score", _f32), ("bbox_x", _f32), ("bbox_y", _f32), ("bbox_w", _f32), ("bbox_h", _f32),
])  # fmt: skip
SAMPLE_COLUMNS = ("sample_no", "split", "class_name", "label", "start_frame", "end_frame", "start_s", "end_s",
                  "handedness", "hand_track_id", "object_label", "object_track_id", "source", "status",
                  "review_method", "confidence", "annotation_revision")  # fmt: skip
ID_COLUMNS = ("id", "annotation_id", "event_id", "video_id", "session_id", "model_version_id", "run_id",
              "hand_run_id", "object_run_id")  # fmt: skip


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "dataset"


def filename(dataset: Dataset, version: DatasetVersion, fmt: ExportFormat) -> str:
    return f"{slug(dataset.name)}-v{version.number}-{fmt.value}.zip"


def _s(v: Any) -> Any:
    return str(v) if isinstance(v, uuid.UUID) else v


@dataclass
class Frames:
    """A sample's hand keypoints and object boxes, frame by frame, read from its runs' Parquet files."""

    hands: list[dict[str, Any]] = field(default_factory=list)
    objects: list[dict[str, Any]] = field(default_factory=list)
    key_frame: int = 0


def _window(run: CvRun | None, kind: str, lo: int, hi: int) -> list[dict[str, Any]]:
    if run is None or not (run.output or {}).get(kind):
        return []
    return store.read_window(run.output, kind, lo, hi).to_pylist()


def read_frames(db: Session, samples: list[DatasetVersionSample]) -> dict[uuid.UUID, Frames]:
    """For one video's samples: each sample's hand-track rows and object-track rows in its frame range."""
    out: dict[uuid.UUID, Frames] = {}
    by_run: dict[tuple[uuid.UUID, str], list[DatasetVersionSample]] = defaultdict(list)
    for s in samples:
        by_run[(s.hand_run_id, "hands")].append(s)
        if s.object_run_id and s.object_track_id is not None:
            by_run[(s.object_run_id, "objects")].append(s)
        out[s.id] = Frames(key_frame=(s.start_frame + s.end_frame) // 2)
    for (run_id, kind), group in by_run.items():
        rows = _window(
            db.get(CvRun, run_id), kind, min(s.start_frame for s in group), max(s.end_frame for s in group)
        )
        index: dict[int, dict[int, dict[str, Any]]] = defaultdict(dict)
        for r in rows:
            index[r["track_id"]][r["frame"]] = r
        for s in group:
            track = index.get(s.hand_track_id if kind == "hands" else s.object_track_id, {})  # type: ignore[arg-type]
            picked = [track[f] for f in sorted(track) if s.start_frame <= f <= s.end_frame]
            if kind == "hands":
                out[s.id].hands = picked
                if picked:
                    mid = (s.start_frame + s.end_frame) / 2
                    out[s.id].key_frame = min((r["frame"] for r in picked), key=lambda f: (abs(f - mid), f))
            else:
                out[s.id].objects = picked
    return out


SELECT_BATCH = 40  # frames per ffmpeg run; some ffmpeg builds reject long select expressions


def select_expr(frames: list[int]) -> str:
    """An ffmpeg `select` expression picking exactly these (sorted) frames, runs of consecutive frames as one
    `between` term, so the expression stays short."""
    terms, i = [], 0
    while i < len(frames):
        j = i
        while j + 1 < len(frames) and frames[j + 1] == frames[j] + 1:
            j += 1
        a, b = frames[i], frames[j]
        terms.append(f"eq(n\\,{a})" if a == b else f"between(n\\,{a}\\,{b})")
        i = j + 1
    return "+".join(terms)


def extract_images(video: Video, frames: set[int], work: Path) -> dict[int, bytes]:
    """JPEGs of the given frames, decoded from the raw video (numbered like the proxy and the CV runs)."""
    if not frames:
        return {}
    vdir = work / f"v-{video.id}"
    vdir.mkdir(exist_ok=True)
    source, pattern = frames_mod.download_source(video.storage_key, video.source_kind, vdir)
    out: dict[int, bytes] = {}
    runs = 0

    def extract(chunk: list[int]) -> None:
        nonlocal runs
        runs += 1
        odir = vdir / f"out-{runs}"
        odir.mkdir()
        cmd = [get_settings().ffmpeg_bin, "-v", "error", "-nostdin",
               *input_args(source, pattern, video.fps), "-map", "0:v:0",
               "-vf", f"select='{select_expr(chunk)}'", "-fps_mode", "passthrough", "-q:v", "3", str(odir / "%06d.jpg")]  # fmt: skip
        proc = subprocess.run(cmd, capture_output=True, timeout=1800)
        if proc.returncode != 0:
            if len(chunk) > 1:  # e.g. an expression this ffmpeg can't parse: halve it and try again
                half = len(chunk) // 2
                extract(chunk[:half])
                extract(chunk[half:])
                return
            raise RuntimeError(f"ffmpeg could not extract frame {chunk[0]} of {video.original_filename}: "
                               f"{proc.stderr.decode(errors='replace')[:300]}")  # fmt: skip
        for f, path in zip(chunk, sorted(odir.glob("*.jpg")), strict=False):
            out[f] = path.read_bytes()

    wanted = sorted(frames)
    for start in range(0, len(wanted), SELECT_BATCH):
        extract(wanted[start : start + SELECT_BATCH])
    return out


def _hand_rows(s: DatasetVersionSample, fr: Frames) -> list[dict[str, Any]]:
    return [{"sample_id": str(s.id), "sample_no": s.sample_no, "frame": r["frame"], "timestamp_s": r["timestamp_s"],
             "handedness": r["handedness"], "confidence": r["confidence"], "bbox_x": r["bbox_x"], "bbox_y": r["bbox_y"],
             "bbox_w": r["bbox_w"], "bbox_h": r["bbox_h"], "kp_x": r["kp_x"], "kp_y": r["kp_y"], "kp_z": r["kp_z"]}
            for r in fr.hands]  # fmt: skip


def _object_rows(s: DatasetVersionSample, fr: Frames) -> list[dict[str, Any]]:
    return [{"sample_id": str(s.id), "sample_no": s.sample_no, "frame": r["frame"], "timestamp_s": r["timestamp_s"],
             "label": r["label"], "score": r["score"], "bbox_x": r["bbox_x"], "bbox_y": r["bbox_y"],
             "bbox_w": r["bbox_w"], "bbox_h": r["bbox_h"]} for r in fr.objects]  # fmt: skip


def sample_record(s: DatasetVersionSample, video: Video) -> dict[str, Any]:
    return {
        "sample_id": str(s.id), "sample_no": s.sample_no, "split": s.split, "class": s.class_name, "label": s.label,
        "start_frame": s.start_frame, "end_frame": s.end_frame, "start_s": s.start_s, "end_s": s.end_s,
        "handedness": s.handedness, "hand_track_id": s.hand_track_id, "fingers": list(s.fingers),
        "object": {"label": s.object_label, "track_id": s.object_track_id} if s.object_label else None,
        "confidence": s.confidence, "source": s.source, "review": {"status": s.status, "method": s.review_method},
        "annotation": {"id": str(s.annotation_id), "revision": s.annotation_revision}, "event_id": str(s.event_id),
        "model_version_id": str(s.model_version_id),
        "runs": {"classification": str(s.run_id), "hand_tracking": str(s.hand_run_id),
                 "object_detection": _s(s.object_run_id)},
        "video": {"id": str(video.id), "filename": video.original_filename, "sha256": video.sha256,
                  "storage_key": video.storage_key, "width": video.width, "height": video.height, "fps": video.fps},
        "session_id": _s(s.session_id), "group": s.group_key,
    }  # fmt: skip


def manifest(db: Session, dataset: Dataset, version: DatasetVersion, fmt: ExportFormat) -> dict[str, Any]:
    mvs = db.scalars(select(ModelVersion).where(ModelVersion.id.in_(version.model_version_ids))).all() if version.model_version_ids else []  # fmt: skip
    classes = sorted({c for c in version.counts.get("classes", {})})
    taxonomy = {c.name: c for c in db.scalars(select(MovementClass).where(MovementClass.name.in_(classes)))} if classes else {}  # fmt: skip
    return {
        "format": fmt.value,
        "generator": "Ego Labs",
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": {"id": str(dataset.id), "name": dataset.name, "description": dataset.description},
        "version": {"id": str(version.id), "number": version.number, "content_hash": version.content_hash,
                    "hash_version": version.inputs.get("hash_version"), "parent_version_id": _s(version.parent_version_id),
                    "spec": version.spec, "as_of": version.inputs.get("as_of"), "runs": version.inputs.get("runs", []),
                    "videos": len(version.inputs.get("videos", [])), "sample_count": version.sample_count,
                    "counts": version.counts, "created_at": version.created_at.isoformat(),
                    "built_at": version.built_at.isoformat() if version.built_at else None},
        "model_versions": [{"id": str(m.id), "name": m.name, "version": m.version, "kind": m.kind,
                            "adapter": m.adapter, "config": m.config} for m in mvs],
        "classes": [{"name": n, "label": taxonomy[n].label if n in taxonomy else n,
                     "description": taxonomy[n].description if n in taxonomy else ""} for n in classes],
        "keypoint_schema": keypoints.SCHEMA,
    }  # fmt: skip


class Writer:
    """Collects one format's files in a work directory, then zips them."""

    def __init__(self, root: Path, meta: dict[str, Any]):
        self.root, self.meta = root, meta
        self.files = 0

    def path(self, rel: str) -> Path:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def write_json(self, rel: str, obj: Any) -> None:
        self.path(rel).write_text(json.dumps(obj, indent=1, default=str))

    def add(self, s: DatasetVersionSample, video: Video, fr: Frames, image: bytes | None) -> None:
        raise NotImplementedError

    def close(self) -> None:
        self.write_json("manifest.json", self.meta)


class JsonlWriter(Writer):
    def __init__(self, root: Path, meta: dict[str, Any]):
        super().__init__(root, meta)
        self._f = self.path("samples.jsonl").open("w")

    def add(self, s, video, fr, image):  # type: ignore[no-untyped-def]
        rec = sample_record(s, video)
        rec["keypoints"] = [
            {k: v for k, v in r.items() if k not in ("sample_id", "sample_no")} for r in _hand_rows(s, fr)
        ]
        rec["object_boxes"] = [
            {k: v for k, v in r.items() if k not in ("sample_id", "sample_no")} for r in _object_rows(s, fr)
        ]
        self._f.write(json.dumps(rec, default=str) + "\n")

    def close(self) -> None:
        self._f.close()
        super().close()


class ParquetWriter(Writer):
    """samples / keypoints / objects Parquet files, written in batches."""

    def __init__(self, root: Path, meta: dict[str, Any], extra: bool = False):
        super().__init__(root, meta)
        self._samples: list[dict[str, Any]] = []
        self._kp = pq.ParquetWriter(self.path("keypoints.parquet"), KEYPOINT_SCHEMA, compression="zstd")
        self._obj = pq.ParquetWriter(self.path("objects.parquet"), OBJECT_SCHEMA, compression="zstd")
        self._evidence = self.path("evidence.jsonl").open("w") if extra else None
        self._videos: dict[str, dict[str, Any]] = {}
        self._splits: dict[str, list[str]] = {s: [] for s in SPLITS}
        self.extra = extra

    def add(self, s, video, fr, image):  # type: ignore[no-untyped-def]
        row = {c: _s(getattr(s, c)) for c in ID_COLUMNS} | {c: getattr(s, c) for c in SAMPLE_COLUMNS}
        row["fingers"] = ",".join(s.fingers)
        row["key_frame"] = fr.key_frame
        row["video_sha256"], row["video_storage_key"] = video.sha256, video.storage_key
        self._samples.append(row)
        if rows := _hand_rows(s, fr):
            self._kp.write_table(pa.Table.from_pylist(rows, KEYPOINT_SCHEMA))
        if rows := _object_rows(s, fr):
            self._obj.write_table(pa.Table.from_pylist(rows, OBJECT_SCHEMA))
        self._splits[s.split].append(str(s.id))
        if self.extra:
            self._videos.setdefault(str(video.id), {"id": str(video.id)})

    def evidence(self, s: DatasetVersionSample, ev: dict[str, Any]) -> None:
        if self._evidence:
            self._evidence.write(
                json.dumps({"sample_id": str(s.id), "event_id": str(s.event_id), **ev}, default=str) + "\n"
            )

    def close(self) -> None:
        pq.write_table(pa.Table.from_pylist(self._samples) if self._samples else pa.table({}), self.path("samples.parquet"),
                       compression="zstd")  # fmt: skip
        self._kp.close()
        self._obj.close()
        if self._evidence:
            self._evidence.close()
            for name, ids in self._splits.items():
                self.path(f"splits/{name}.txt").write_text("".join(f"{i}\n" for i in ids))
        super().close()


class CocoWriter(Writer):
    """COCO keypoint annotations per split, one key-frame image per sample."""

    def __init__(self, root: Path, meta: dict[str, Any]):
        super().__init__(root, meta)
        self.categories = {c["name"]: i + 1 for i, c in enumerate(meta["classes"])}
        self.images: dict[str, list[dict[str, Any]]] = {s: [] for s in SPLITS}
        self.annotations: dict[str, list[dict[str, Any]]] = {s: [] for s in SPLITS}

    def add(self, s, video, fr, image):  # type: ignore[no-untyped-def]
        w, h = video.width or 0, video.height or 0
        name = f"images/{s.sample_no:08d}.jpg"
        if image:
            self.path(name).write_bytes(image)
        image_id = s.sample_no + 1
        self.images[s.split].append({"id": image_id, "file_name": name, "width": w, "height": h,
                                     "video_id": str(video.id), "video_sha256": video.sha256, "frame": fr.key_frame})  # fmt: skip
        hand = next((r for r in fr.hands if r["frame"] == fr.key_frame), None)
        kps: list[float] = []
        bbox = [0.0, 0.0, 0.0, 0.0]
        if hand:
            for x, y in zip(hand["kp_x"], hand["kp_y"], strict=True):
                kps += [round(x * w, 2), round(y * h, 2), 2]
            bbox = [round(hand["bbox_x"] * w, 2), round(hand["bbox_y"] * h, 2), round(hand["bbox_w"] * w, 2),
                    round(hand["bbox_h"] * h, 2)]  # fmt: skip
        obj = next((r for r in fr.objects if r["frame"] == fr.key_frame), None)
        self.annotations[s.split].append({
            "id": image_id, "image_id": image_id, "category_id": self.categories.get(s.class_name, 0),
            "keypoints": kps or [0] * 63, "num_keypoints": 21 if kps else 0, "bbox": bbox,
            "area": round(bbox[2] * bbox[3], 2), "iscrowd": 0,
            "attributes": {"sample_id": str(s.id), "class": s.class_name, "start_frame": s.start_frame,
                           "end_frame": s.end_frame, "start_s": s.start_s, "end_s": s.end_s, "handedness": s.handedness,
                           "object_label": s.object_label,
                           "object_bbox": [round(obj["bbox_x"] * w, 2), round(obj["bbox_y"] * h, 2),
                                           round(obj["bbox_w"] * w, 2), round(obj["bbox_h"] * h, 2)] if obj else None,
                           "source": s.source, "status": s.status, "confidence": s.confidence,
                           "annotation_id": str(s.annotation_id), "event_id": str(s.event_id)},
        })  # fmt: skip

    def close(self) -> None:
        cats = [{"id": i, "name": n, "supercategory": "movement", "keypoints": list(keypoints.KEYPOINT_NAMES),
                 "skeleton": [[a + 1, b + 1] for a, b in keypoints.CONNECTIONS]} for n, i in self.categories.items()]  # fmt: skip
        info = {"description": f"{self.meta['dataset']['name']} v{self.meta['version']['number']}",
                "version": str(self.meta["version"]["number"]), "content_hash": self.meta["version"]["content_hash"],
                "date_created": self.meta["generated_at"]}  # fmt: skip
        for split in SPLITS:
            self.write_json(f"annotations/{split}.json", {"info": info, "licenses": [], "categories": cats,
                                                          "images": self.images[split],
                                                          "annotations": self.annotations[split]})  # fmt: skip
        super().close()


class WebDatasetWriter(Writer):
    def __init__(self, root: Path, meta: dict[str, Any], shard_size: int):
        super().__init__(root, meta)
        self.shard_size = shard_size
        self._tars: dict[str, tarfile.TarFile] = {}
        self._counts: dict[str, int] = defaultdict(int)

    def _tar(self, split: str) -> tarfile.TarFile:
        n = self._counts[split]
        if n % self.shard_size == 0:
            if split in self._tars:
                self._tars[split].close()
            self._tars[split] = tarfile.open(self.path(f"{split}-{n // self.shard_size:06d}.tar"), "w")  # noqa: SIM115 (closed in close())
        return self._tars[split]

    def _put(self, tar: tarfile.TarFile, name: str, data: bytes) -> None:
        info = tarfile.TarInfo(name)
        info.size, info.mtime = len(data), 0
        tar.addfile(info, io.BytesIO(data))

    def add(self, s, video, fr, image):  # type: ignore[no-untyped-def]
        tar = self._tar(s.split)
        key = f"{s.sample_no:08d}"
        self._put(tar, f"{key}.json", json.dumps(sample_record(s, video), default=str).encode())
        if image:
            self._put(tar, f"{key}.jpg", image)
        rows = [
            {k: v for k, v in r.items() if k not in ("sample_id", "sample_no")} for r in _hand_rows(s, fr)
        ]
        self._put(tar, f"{key}.keypoints.json", json.dumps(rows, default=str).encode())
        self._counts[s.split] += 1

    def close(self) -> None:
        for t in self._tars.values():
            t.close()
        super().close()


def _videos_provenance(db: Session, video_ids: set[uuid.UUID]) -> list[dict[str, Any]]:
    out = []
    for v in db.scalars(select(Video).where(Video.id.in_(video_ids)).order_by(Video.id)):
        sess = db.get(CaptureSession, v.session_id) if v.session_id else None
        dev = db.get(Device, sess.device_id) if sess and sess.device_id else None
        op = db.get(Operator, sess.operator_id) if sess and sess.operator_id else None
        out.append({"id": str(v.id), "filename": v.original_filename, "sha256": v.sha256, "storage_key": v.storage_key,
                    "size_bytes": v.size_bytes, "source_kind": v.source_kind.value, "source_path": v.source_path,
                    "upload_id": _s(v.upload_id), "duration_s": v.duration_s, "width": v.width, "height": v.height,
                    "fps": v.fps, "codec": v.codec, "frame_count": v.frame_count, "quality_flags": list(v.quality_flags or []),
                    "camera_metadata": v.camera_metadata,
                    "session": {"id": str(sess.id), "name": sess.name, "environment": sess.environment, "task": sess.task,
                                "location": sess.location} if sess else None,
                    "device": {"id": str(dev.id), "name": dev.name, "kind": dev.kind} if dev else None,
                    "operator": {"id": str(op.id), "name": op.name} if op else None})  # fmt: skip
    return out


def write_export(db: Session, dataset: Dataset, version: DatasetVersion, fmt: ExportFormat, work: Path,
                 ctx: JobContext | None = None) -> tuple[Path, int]:  # fmt: skip
    """Write the version in `fmt` under `work` and zip it. Returns (zip path, files in it)."""
    meta = manifest(db, dataset, version, fmt)
    root = work / "out"
    root.mkdir()
    writer: Writer
    if fmt == ExportFormat.jsonl:
        writer = JsonlWriter(root, meta)
    elif fmt == ExportFormat.parquet:
        writer = ParquetWriter(root, meta)
    elif fmt == ExportFormat.egolabs:
        writer = ParquetWriter(root, meta, extra=True)
    elif fmt == ExportFormat.coco:
        writer = CocoWriter(root, meta)
    else:
        writer = WebDatasetWriter(root, meta, get_settings().export_shard_samples)
    video_ids: set[uuid.UUID] = set()
    batch: list[DatasetVersionSample] = []

    def flush(group: list[DatasetVersionSample]) -> None:
        if not group:
            return
        video = db.get(Video, group[0].video_id)
        assert video is not None
        frames = read_frames(db, group)
        images = (
            extract_images(video, {frames[s.id].key_frame for s in group}, work)
            if fmt in IMAGE_FORMATS
            else {}
        )
        events = {e.id: e for e in db.scalars(select(MovementEvent).where(MovementEvent.id.in_([s.event_id for s in group])))} \
            if fmt == ExportFormat.egolabs else {}  # fmt: skip
        for s in group:
            fr = frames[s.id]
            writer.add(s, video, fr, images.get(fr.key_frame))
            if isinstance(writer, ParquetWriter) and s.event_id in events:
                writer.evidence(s, events[s.event_id].evidence or {})
        if ctx:
            ctx.info("Exported samples", video=video.original_filename, samples=len(group))

    for s in samples_of(db, version.id):
        if batch and s.video_id != batch[0].video_id:
            flush(batch)
            batch = []
        batch.append(s)
        video_ids.add(s.video_id)
    flush(batch)
    if fmt == ExportFormat.egolabs:
        writer.write_json("videos.json", _videos_provenance(db, video_ids))
    writer.close()
    zpath = work / "export.zip"
    files = 0
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(root.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(root).as_posix(),
                        compress_type=zipfile.ZIP_STORED if p.suffix in (".jpg", ".tar", ".parquet") else zipfile.ZIP_DEFLATED)  # fmt: skip
                files += 1
    return zpath, files


@job_handler("datasets.export")
def export_version(ctx: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
    export_id = uuid.UUID(payload["export_id"])
    settings = get_settings()
    try:
        with ctx.session() as db:
            ex = db.get(DatasetExport, export_id)
            if ex is None:
                raise LookupError(f"export {export_id} not found")
            version = db.get(DatasetVersion, ex.version_id)
            assert version is not None
            if version.status != BuildStatus.ready:
                raise RuntimeError(f"version {version.id} is {version.status.value}, not ready")
            dataset = db.get(Dataset, version.dataset_id)
            assert dataset is not None
            ctx.info("Exporting", dataset=dataset.name, version=version.number, format=ex.format.value,
                     samples=version.sample_count)  # fmt: skip
            with tempfile.TemporaryDirectory(dir=settings.work_dir, prefix="egolabs-export-") as tmp:
                zpath, files = write_export(db, dataset, version, ex.format, Path(tmp), ctx)
                key = (
                    f"exports/{dataset.id}/v{version.number}/{ex.id}/{filename(dataset, version, ex.format)}"
                )
                digest = storage.sha256_file(zpath)
                size = zpath.stat().st_size
                storage.upload(zpath, settings.s3_bucket_derived, key, "application/zip")
            ex.storage_key, ex.size_bytes, ex.sha256, ex.files = key, size, digest, files
            ex.status, ex.finished_at = BuildStatus.ready, datetime.now(UTC)
            db.add(LineageEdge(parent_type="dataset_version", parent_id=version.id, child_type="dataset_export",
                               child_id=ex.id, relation="exported_as", job_id=ctx.job_id))  # fmt: skip
            record_event(db, "dataset.exported", f"{dataset.name} v{version.number} exported as {ex.format.value}",
                         entity_type="dataset_export", entity_id=ex.id, data={"version_id": str(version.id)})  # fmt: skip
            db.commit()
            ctx.info("Export stored", key=key, size_bytes=size, files=files, sha256=digest)
            return {"key": key, "size_bytes": size, "files": files, "sha256": digest}
    except Exception as exc:
        with ctx.session() as db:
            e = db.get(DatasetExport, export_id)
            if e is not None and e.status == BuildStatus.building:
                e.status, e.error, e.finished_at = BuildStatus.failed, str(exc)[:2000], datetime.now(UTC)
                db.commit()
        raise
