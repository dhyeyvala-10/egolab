"""
Building a dataset version (spec Phase 6, principle 6: reproducible from its recorded inputs, filters, and
model versions).

A version is created from a spec (filters + split). Creating it pins its inputs:

- `as_of`: the instant whose state it reads. Review status comes from the review log (the last change at or
  before `as_of`), and a correction's content from its annotation revision at `as_of`, so reviews and
  corrections made later never change it.
- `videos`: the videos the video-level filters matched (session, device, environment, quality flags), each
  with the session and operator it had then (for grouped splits).
- `runs`: each video's latest successful classification run then.

The worker then resolves the samples from those inputs, splits them, and hashes them. A sample is a movement
event as it stood at `as_of`: a prediction, or a person's correction in its place. Rebuilding from the same
spec and inputs gives the same samples in the same order, so the same content hash.

Splits are deterministic: each group (session, operator, video, or the sample itself) goes to the split its
`sha256(seed:group)` falls in, so a group never spans two splits.
"""

import hashlib
import json
import uuid
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, insert, select, text
from sqlalchemy.orm import Session

from egolabs.annotations import EVENT_DATA_KEYS, class_for_segment
from egolabs.config import get_settings
from egolabs.cv import frames as frames_mod
from egolabs.events import record_event
from egolabs.models import (
    AnnotationSource,
    BuildStatus,
    CaptureSession,
    CvRun,
    CvRunKind,
    CvRunStatus,
    Dataset,
    DatasetVersion,
    DatasetVersionCheck,
    DatasetVersionSample,
    LineageEdge,
    MovementClass,
    ReviewMethod,
    SplitGroup,
    Video,
    VideoStatus,
)
from egolabs.schemas.datasets import DatasetFilters, DatasetSpec, SplitSpec
from egolabs.worker.runtime import JobContext, job_handler

HASH_VERSION = "egolabs-dataset-v1"
HUMAN_METHODS = {m.value for m in (ReviewMethod.individual, ReviewMethod.bulk, ReviewMethod.correction,
                                   ReviewMethod.inspector)}  # fmt: skip
SPLITS = ("train", "val", "test")
BATCH = 1000

# The fields a sample's content hash covers, in order (derived values like seconds are left out).
HASHED = ("annotation_id", "annotation_revision", "event_id", "video_id", "class_name", "label", "start_frame",
          "end_frame", "handedness", "hand_track_id", "fingers", "object_label", "object_track_id", "source",
          "status", "review_method", "confidence", "model_version_id", "run_id", "hand_run_id", "object_run_id",
          "split", "group_key")  # fmt: skip


@dataclass
class Sample:
    annotation_id: uuid.UUID
    annotation_revision: int
    event_id: uuid.UUID
    video_id: uuid.UUID
    session_id: uuid.UUID | None
    class_name: str
    label: str
    start_frame: int
    end_frame: int
    start_s: float
    end_s: float
    handedness: str
    hand_track_id: int
    fingers: list[str]
    object_label: str | None
    object_track_id: int | None
    source: str
    status: str
    review_method: str | None
    confidence: float | None
    model_version_id: uuid.UUID
    run_id: uuid.UUID
    hand_run_id: uuid.UUID
    object_run_id: uuid.UUID | None
    split: str = ""
    group_key: str = ""


def _plain(v: Any) -> Any:
    if isinstance(v, uuid.UUID):
        return str(v)
    if hasattr(v, "value"):
        return v.value
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    return v


def canonical(sample: Any) -> bytes:
    """One sample's hashed content as a canonical JSON line (works for `Sample` and stored rows alike)."""
    return (json.dumps([_plain(getattr(sample, f)) for f in HASHED], separators=(",", ":"), ensure_ascii=False)
            + "\n").encode()  # fmt: skip


class Hasher:
    def __init__(self) -> None:
        self._h = hashlib.sha256((HASH_VERSION + "\n").encode())
        self.count = 0

    def add(self, sample: Any) -> None:
        self._h.update(canonical(sample))
        self.count += 1

    def hexdigest(self) -> str:
        return self._h.hexdigest()


# --- inputs --------------------------------------------------------------------------------------------


def resolve_inputs(db: Session, filters: DatasetFilters) -> dict[str, Any]:
    """Pin what a new version is built from: now, the matching videos (with session/operator), their runs."""
    as_of: datetime = db.scalar(select(func.now()))  # the database's clock, which stamps every row
    stmt = (
        select(Video.id, Video.session_id, CaptureSession.operator_id)
        .outerjoin(CaptureSession, CaptureSession.id == Video.session_id)
        .where(Video.status == VideoStatus.ready)
    )
    if filters.session_ids:
        stmt = stmt.where(Video.session_id.in_(filters.session_ids))
    if filters.device_ids:
        stmt = stmt.where(CaptureSession.device_id.in_(filters.device_ids))
    if filters.environments:
        stmt = stmt.where(CaptureSession.environment.in_(filters.environments))
    if filters.video_ids:
        stmt = stmt.where(Video.id.in_(filters.video_ids))
    if filters.exclude_quality_flags:
        stmt = stmt.where(~Video.quality_flags.overlap(filters.exclude_quality_flags))
    videos = [{"id": str(v), "session_id": str(s) if s else None, "operator_id": str(o) if o else None}
              for v, s, o in db.execute(stmt.order_by(Video.id))]  # fmt: skip
    runs = []
    if videos:
        latest = (
            select(CvRun.id)
            .distinct(CvRun.video_id)
            .where(
                CvRun.video_id.in_([uuid.UUID(v["id"]) for v in videos]),
                CvRun.kind == CvRunKind.movement.value,
                CvRun.status == CvRunStatus.succeeded,
                CvRun.finished_at <= as_of,
            )  # fmt: skip
            .order_by(CvRun.video_id, CvRun.finished_at.desc(), CvRun.id)
        )
        runs = sorted(str(r) for r in db.scalars(latest))
    return {"as_of": as_of.isoformat(), "videos": videos, "runs": runs, "hash_version": HASH_VERSION}


# --- samples as of -------------------------------------------------------------------------------------

_SQL = text(
    """
WITH cand AS (
  SELECT e.* FROM movement_events e
  WHERE e.run_id = ANY(CAST(:run_ids AS uuid[])) AND e.created_at <= :as_of
    AND (e.superseded_at IS NULL OR e.superseded_at > :as_of)
), last_review AS (
  SELECT DISTINCT ON (r.event_id) r.event_id, r.to_status, r.method
  FROM movement_event_reviews r JOIN cand c ON c.id = r.event_id
  WHERE r.created_at <= :as_of
  ORDER BY r.event_id, r.created_at DESC, r.id DESC
), first_review AS (
  SELECT DISTINCT ON (r.event_id) r.event_id, r.from_status
  FROM movement_event_reviews r JOIN cand c ON c.id = r.event_id
  ORDER BY r.event_id, r.created_at, r.id
), snap AS (
  SELECT DISTINCT ON (v.annotation_id) v.annotation_id, v.revision, v.snapshot
  FROM annotation_revisions v JOIN cand c ON c.annotation_id = v.annotation_id
  WHERE v.created_at <= :as_of
  ORDER BY v.annotation_id, v.revision DESC
), rows AS (
  SELECT c.id AS event_id, c.annotation_id, c.video_id, c.run_id, c.hand_run_id, c.object_run_id,
         c.model_version_id, c.source, c.confidence, c.hand_track_id, c.handedness, c.fingers,
         c.object_label, c.object_track_id, mc.name AS event_class,
         COALESCE(lr.to_status, fr.from_status, c.status) AS status,
         CASE WHEN lr.event_id IS NOT NULL THEN lr.method WHEN fr.event_id IS NULL THEN c.review_method END
           AS review_method,
         CASE WHEN c.source = 'auto' THEN a.label ELSE COALESCE(s.snapshot ->> 'label', a.label) END AS label,
         CASE WHEN c.source = 'auto' THEN a.frame_start
              ELSE COALESCE((s.snapshot ->> 'frame_start')::int, a.frame_start) END AS start_frame,
         CASE WHEN c.source = 'auto' THEN a.frame_end
              ELSE COALESCE((s.snapshot ->> 'frame_end')::int, a.frame_end) END AS end_frame,
         CASE WHEN c.source = 'auto' THEN a.data ELSE COALESCE(s.snapshot -> 'data', a.data) END AS data,
         COALESCE(s.revision, 1) AS revision
  FROM cand c
  JOIN annotations a ON a.id = c.annotation_id
  JOIN movement_classes mc ON mc.id = c.class_id
  LEFT JOIN last_review lr ON lr.event_id = c.id
  LEFT JOIN first_review fr ON fr.event_id = c.id
  LEFT JOIN snap s ON s.annotation_id = c.annotation_id
)
SELECT * FROM rows ORDER BY video_id, start_frame, end_frame, annotation_id
"""
)


def _group(group_by: SplitGroup, video: dict[str, Any], annotation_id: uuid.UUID) -> str:
    """The group a sample is split with; falls back to the next-finer group when one is unknown."""
    if group_by == SplitGroup.operator and video.get("operator_id"):
        return f"operator:{video['operator_id']}"
    if group_by in (SplitGroup.operator, SplitGroup.session) and video.get("session_id"):
        return f"session:{video['session_id']}"
    if group_by in (SplitGroup.operator, SplitGroup.session, SplitGroup.video):
        return f"video:{video['id']}"
    return f"sample:{annotation_id}"


def split_of(group_key: str, split: SplitSpec) -> str:
    u = int(hashlib.sha256(f"{split.seed}:{group_key}".encode()).hexdigest()[:16], 16) / 2**64
    if u < split.train:
        return "train"
    if u < split.train + split.val:
        return "val"
    return "test"


def _keep(s: Sample, f: DatasetFilters) -> bool:
    if f.classes and s.class_name not in f.classes:
        return False
    if s.status not in f.statuses:
        return False
    if f.human_verified_only and not (s.status == "confirmed" and s.review_method in HUMAN_METHODS):
        return False
    if s.source == AnnotationSource.auto.value and s.confidence is not None:  # model confidence: predictions
        if f.min_confidence is not None and s.confidence < f.min_confidence:
            return False
        if f.max_confidence is not None and s.confidence > f.max_confidence:
            return False
    if f.handedness and s.handedness not in f.handedness:
        return False
    if f.object_labels and s.object_label not in f.object_labels:
        return False
    if f.require_object is None:
        return True
    return bool(s.object_label) == f.require_object


def iter_samples(
    db: Session, spec: DatasetSpec, inputs: dict[str, Any], limit: int | None = None
) -> Iterator[Sample]:
    """The version's samples in their canonical order (video, start, end, annotation id), with splits."""
    if not inputs.get("runs"):
        return
    videos = {v["id"]: v for v in inputs["videos"]}
    classes = list(db.scalars(select(MovementClass)))
    timestamps: dict[uuid.UUID, list[float]] = {}

    def seconds(video_id: uuid.UUID, frame: int) -> float:
        if video_id not in timestamps:
            video = db.get(Video, video_id)
            timestamps[video_id] = frames_mod.video_timestamps(video) if video else []
        ts = timestamps[video_id]
        return float(ts[frame]) if frame < len(ts) else frame / 30.0

    rows = db.execute(_SQL.bindparams(run_ids=inputs["runs"], as_of=datetime.fromisoformat(inputs["as_of"])),
                      execution_options={"yield_per": 2000})  # fmt: skip
    n = 0
    for r in rows:
        data = r.data or {}
        if r.source == AnnotationSource.auto.value:
            class_name = r.event_class
            hand, fingers, obj, obj_track = r.handedness, list(r.fingers), r.object_label, r.object_track_id
        else:
            cls = class_for_segment(r.label, data, classes)
            class_name = cls.name if cls else r.event_class
            fields = {k: data[k] for k in EVENT_DATA_KEYS if k in data}
            hand = fields.get("handedness", r.handedness)
            fingers = list(fields.get("fingers", r.fingers))
            obj = fields.get("object_label", r.object_label)
            obj_track = fields.get("object_track_id", r.object_track_id)
        video = videos.get(str(r.video_id), {"id": str(r.video_id)})
        s = Sample(annotation_id=r.annotation_id, annotation_revision=r.revision, event_id=r.event_id,
                   video_id=r.video_id, session_id=uuid.UUID(video["session_id"]) if video.get("session_id") else None,
                   class_name=class_name, label=r.label, start_frame=r.start_frame, end_frame=r.end_frame,
                   start_s=seconds(r.video_id, r.start_frame), end_s=seconds(r.video_id, r.end_frame),
                   handedness=hand, hand_track_id=r.hand_track_id, fingers=fingers, object_label=obj,
                   object_track_id=obj_track, source=r.source, status=r.status, review_method=r.review_method,
                   confidence=r.confidence, model_version_id=r.model_version_id, run_id=r.run_id,
                   hand_run_id=r.hand_run_id, object_run_id=r.object_run_id)  # fmt: skip
        if not _keep(s, spec.filters):
            continue
        s.group_key = _group(spec.split.group_by, video, s.annotation_id)
        s.split = split_of(s.group_key, spec.split)
        yield s
        n += 1
        if limit is not None and n >= limit:
            return


@dataclass
class Tally:
    splits: dict[str, int] = field(default_factory=lambda: dict.fromkeys(SPLITS, 0))
    groups: dict[str, set[str]] = field(default_factory=lambda: {s: set() for s in SPLITS})
    classes: dict[str, dict[str, int]] = field(default_factory=dict)
    statuses: dict[str, int] = field(default_factory=lambda: defaultdict(int))  # type: ignore[arg-type]
    sources: dict[str, int] = field(default_factory=lambda: defaultdict(int))  # type: ignore[arg-type]
    videos: set[str] = field(default_factory=set)

    def add(self, s: Sample) -> None:
        self.splits[s.split] += 1
        self.groups[s.split].add(s.group_key)
        self.classes.setdefault(s.class_name, dict.fromkeys(SPLITS, 0))[s.split] += 1
        self.statuses[s.status] += 1
        self.sources[s.source] += 1
        self.videos.add(str(s.video_id))

    def counts(self) -> dict[str, Any]:
        return {"splits": self.splits, "groups": {k: len(v) for k, v in self.groups.items()},
                "classes": dict(sorted(self.classes.items())), "statuses": dict(self.statuses),
                "sources": dict(self.sources), "videos": len(self.videos)}  # fmt: skip

    def warnings(self, split: SplitSpec) -> list[str]:
        out = []
        for name in SPLITS:
            if getattr(split, name) > 0 and self.splits[name] == 0 and sum(self.splits.values()):
                out.append(f"No samples landed in {name}: there are too few {split.group_by.value} groups "
                           f"({sum(len(g) for g in self.groups.values())}) for these ratios.")  # fmt: skip
        leaked = sum(len(g) for g in self.groups.values()) - len(set().union(*self.groups.values()))
        if leaked:  # can't happen by construction; checked anyway
            out.append(f"{leaked} groups appear in more than one split.")
        return out


def preview(db: Session, spec: DatasetSpec) -> dict[str, Any]:
    limit = get_settings().dataset_preview_max
    inputs = resolve_inputs(db, spec.filters)
    tally, sample = Tally(), []
    n = 0
    for s in iter_samples(db, spec, inputs, limit=limit + 1):
        n += 1
        if n > limit:
            break
        tally.add(s)
        if len(sample) < 20:
            sample.append({k: getattr(s, k) for k in ("annotation_id", "event_id", "video_id", "class_name",
                                                      "start_frame", "end_frame", "status", "source", "confidence",
                                                      "split")})  # fmt: skip
    return {"videos": len(inputs["videos"]), "runs": len(inputs["runs"]), "sample_count": min(n, limit),
            "truncated": n > limit, "counts": tally.counts(), "sample": sample, "warnings": tally.warnings(spec.split)}  # fmt: skip


# --- creating and building -----------------------------------------------------------------------------


def create_version(db: Session, dataset: Dataset, spec: DatasetSpec, user_id: uuid.UUID | None,
                   note: str | None = None) -> DatasetVersion:  # fmt: skip
    """Number the version, pin its inputs now, and leave it `building` for the worker."""
    locked = db.get(Dataset, dataset.id, with_for_update=True)
    assert locked is not None
    last = db.scalar(
        select(DatasetVersion)
        .where(DatasetVersion.dataset_id == dataset.id)
        .order_by(DatasetVersion.number.desc())
        .limit(1)
    )
    version = DatasetVersion(dataset_id=dataset.id, number=(last.number + 1) if last else 1,
                             parent_version_id=last.id if last else None, status=BuildStatus.building,
                             spec=spec.model_dump(mode="json"), inputs=resolve_inputs(db, spec.filters),
                             created_by=user_id, note=note)  # fmt: skip
    db.add(version)
    db.flush()
    return version


def _model_versions(db: Session, samples_mv: set[uuid.UUID], run_ids: set[uuid.UUID]) -> list[uuid.UUID]:
    """The classifier versions of the samples plus the hand and object model versions they read."""
    ids = set(samples_mv)
    if run_ids:
        ids |= {m for m in db.scalars(select(CvRun.model_version_id).where(CvRun.id.in_(run_ids))) if m}
    return sorted(ids, key=str)


@job_handler("datasets.build_version")
def build_version(ctx: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
    version_id = uuid.UUID(payload["version_id"])
    try:
        with ctx.session() as db:
            version = db.get(DatasetVersion, version_id)
            if version is None:
                raise LookupError(f"dataset version {version_id} not found")
            if version.status != BuildStatus.building:
                raise RuntimeError(f"dataset version {version_id} is {version.status.value}, not building")
            spec, inputs = DatasetSpec.model_validate(version.spec), dict(version.inputs)
            ctx.info("Building dataset version", number=version.number, as_of=inputs["as_of"],
                     videos=len(inputs["videos"]), runs=len(inputs["runs"]))  # fmt: skip
            hasher, tally = Hasher(), Tally()
            mvs: set[uuid.UUID] = set()
            input_runs: set[uuid.UUID] = set()
            batch: list[dict[str, Any]] = []
            for s in iter_samples(db, spec, inputs):
                hasher.add(s)
                tally.add(s)
                mvs.add(s.model_version_id)
                input_runs.add(s.hand_run_id)
                if s.object_run_id:
                    input_runs.add(s.object_run_id)
                batch.append(
                    {**asdict(s), "id": uuid.uuid4(), "version_id": version_id, "sample_no": hasher.count - 1}
                )
                if len(batch) >= BATCH:
                    db.execute(insert(DatasetVersionSample), batch)
                    batch = []
                    if hasher.count % 20000 == 0:
                        ctx.info("Resolved samples", samples=hasher.count)
            if batch:
                db.execute(insert(DatasetVersionSample), batch)
            version.content_hash, version.sample_count = hasher.hexdigest(), hasher.count
            version.counts = tally.counts()
            version.model_version_ids = _model_versions(db, mvs, input_runs)
            version.status, version.built_at, version.job_id = (
                BuildStatus.ready,
                datetime.now(UTC),
                ctx.job_id,
            )
            edges = [("dataset", version.dataset_id, "version_of")]
            if version.parent_version_id:
                edges.append(("dataset_version", version.parent_version_id, "previous_version_of"))
            edges += [("model_version", m, "model_of") for m in version.model_version_ids]
            for parent_type, parent_id, relation in edges:
                db.add(LineageEdge(parent_type=parent_type, parent_id=parent_id, child_type="dataset_version",
                                   child_id=version_id, relation=relation, job_id=ctx.job_id))  # fmt: skip
            dataset = db.get(Dataset, version.dataset_id)
            assert dataset is not None
            record_event(db, "dataset.version_created", f"Dataset {dataset.name} v{version.number} created "
                         f"({hasher.count} samples)", entity_type="dataset_version", entity_id=version_id,
                         data={"dataset_id": str(dataset.id), "hash": version.content_hash})  # fmt: skip
            db.commit()
    except Exception as exc:
        with ctx.session() as db:
            v = db.get(DatasetVersion, version_id)
            if v is not None and v.status == BuildStatus.building:
                v.status, v.error = BuildStatus.failed, str(exc)[:2000]
                db.commit()
        raise
    ctx.info(
        "Dataset version ready",
        samples=hasher.count,
        content_hash=version.content_hash,
        **tally.counts()["splits"],
    )
    return {"samples": hasher.count, "content_hash": hasher.hexdigest()}


def stored_hash(db: Session, version_id: uuid.UUID) -> tuple[str, int]:
    """The hash of the rows a version stored (they must match the recorded content hash)."""
    hasher = Hasher()
    rows = db.scalars(select(DatasetVersionSample).where(DatasetVersionSample.version_id == version_id)
                      .order_by(DatasetVersionSample.sample_no), execution_options={"yield_per": 2000})  # fmt: skip
    for row in rows:
        hasher.add(row)
    return hasher.hexdigest(), hasher.count


def rebuild_hash(db: Session, version: DatasetVersion) -> tuple[str, int]:
    hasher = Hasher()
    for s in iter_samples(db, DatasetSpec.model_validate(version.spec), dict(version.inputs)):
        hasher.add(s)
    return hasher.hexdigest(), hasher.count


@job_handler("datasets.verify_version")
def verify_version(ctx: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
    """Rebuild a version from its recorded spec and inputs; compare with its hash and its stored rows."""
    check_id = uuid.UUID(payload["check_id"])
    try:
        with ctx.session() as db:
            check = db.get(DatasetVersionCheck, check_id)
            if check is None:
                raise LookupError(f"check {check_id} not found")
            version = db.get(DatasetVersion, check.version_id)
            assert version is not None
            rebuilt, n = rebuild_hash(db, version)
            stored, m = stored_hash(db, version.id)
            check.content_hash, check.sample_count = rebuilt, n
            check.matches = rebuilt == version.content_hash == stored and n == m == version.sample_count
            check.status, check.finished_at = BuildStatus.ready, datetime.now(UTC)
            ctx.info("Rebuilt from the recorded spec", recorded=version.content_hash, rebuilt=rebuilt,
                     stored_rows=stored, matches=check.matches)  # fmt: skip
            db.commit()
            return {"matches": check.matches, "rebuilt_hash": rebuilt, "stored_hash": stored, "samples": n}
    except Exception as exc:
        with ctx.session() as db:
            c = db.get(DatasetVersionCheck, check_id)
            if c is not None:
                c.status, c.error, c.finished_at = BuildStatus.failed, str(exc)[:2000], datetime.now(UTC)
                db.commit()
        raise


def samples_of(
    db: Session, version_id: uuid.UUID, ids: Iterable[uuid.UUID] | None = None
) -> Iterator[DatasetVersionSample]:
    stmt = select(DatasetVersionSample).where(DatasetVersionSample.version_id == version_id)
    if ids is not None:
        stmt = stmt.where(DatasetVersionSample.id.in_(list(ids)))
    yield from db.scalars(
        stmt.order_by(DatasetVersionSample.sample_no), execution_options={"yield_per": 2000}
    )
