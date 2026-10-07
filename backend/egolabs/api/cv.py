import uuid
from typing import Annotated

import numpy as np
from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from egolabs.api.deps import CurrentUser, DbSession, Processor
from egolabs.config import get_settings
from egolabs.cv import registry, store
from egolabs.cv import runs as runs_service
from egolabs.cv.adapters.base import AdapterError
from egolabs.cv.features import FINGER_NAMES
from egolabs.models import (
    CvRun,
    CvRunKind,
    CvRunStatus,
    HandTrack,
    ModelVersion,
    ObjectTrack,
    ProcessingHold,
    Video,
    VideoStatus,
)
from egolabs.schemas import Page
from egolabs.schemas.catalog import Ref
from egolabs.schemas.cv import (
    AdapterInfo,
    CvRunCreate,
    CvRunDetail,
    CvRunSummary,
    FingerState,
    FrameHands,
    FrameObjects,
    HandInFrame,
    HandTrackRead,
    ModelVersionRef,
    ObjectInFrame,
    ObjectTrackRead,
    RunFrames,
    RunObjects,
    RunSeries,
    Series,
    SeriesMetric,
    SeriesPoint,
)

router = APIRouter(prefix="/cv", tags=["cv"])

MAX_FRAME_WINDOW = 1800


def _summary(run: CvRun, video_name: str, mv: ModelVersion | None) -> CvRunSummary:
    fields = {f: getattr(run, f) for f in CvRunSummary.model_fields if f not in ("video", "model_version")}
    fields["inputs"] = run.inputs or {}
    return CvRunSummary(
        **fields,
        video=Ref(id=run.video_id, name=video_name),
        model_version=ModelVersionRef.model_validate(mv) if mv else None,
    )


def _get(db: DbSession, run_id: uuid.UUID) -> tuple[CvRun, str, ModelVersion | None]:
    run = db.get(CvRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    video = db.get(Video, run.video_id)
    mv = db.get(ModelVersion, run.model_version_id) if run.model_version_id else None
    return run, video.original_filename if video else "", mv


@router.get("/adapters", response_model=AdapterInfo)
def adapter_info(db: DbSession, _: CurrentUser, kind: CvRunKind = CvRunKind.hand_tracking) -> AdapterInfo:
    """The adapter new runs of `kind` will use. Change it with the settings named in `env`, not code."""
    name, config = registry.configured(kind.value)
    spec = registry.KINDS[kind.value]
    target, runnable, error, detects = registry.target(name, kind.value), True, None, None
    try:
        cls = registry.resolve(name, kind.value)
        runnable = not registry.is_stub(cls)
        if not runnable:
            error = f"{name} is a documented stub, not an implementation"
        fixed = getattr(cls, "classes", None) or getattr(cls, "labels", None)
        detects = list(fixed) if fixed else None
    except AdapterError as exc:
        runnable, error = False, str(exc)
    stubs = []
    for registered in spec.adapters:
        try:
            if registry.is_stub(registry.resolve(registered, kind.value)):
                stubs.append(registered)
        except AdapterError:
            pass
    # The model version is registered by the worker; show the latest one this exact setup produced.
    latest = db.scalar(
        select(ModelVersion)
        .join(CvRun, CvRun.model_version_id == ModelVersion.id)
        .where(CvRun.kind == kind.value, CvRun.adapter == name, CvRun.config == config)
        .order_by(CvRun.created_at.desc())
        .limit(1)
    )
    return AdapterInfo(
        kind=kind, env=spec.env, name=name, target=target, config=config, runnable=runnable, error=error,
        registered=list(spec.adapters), stubs=stubs, detects=detects,
        model_version=ModelVersionRef.model_validate(latest) if latest else None,
    )  # fmt: skip


@router.post("/runs", response_model=list[CvRunSummary], status_code=201)
def create_runs(body: CvRunCreate, db: DbSession, user: Processor) -> list[CvRunSummary]:
    """
    Queue runs on each video with the configured adapters: by default hand tracking and object detection,
    then movement classification on their output once both succeed.
    """
    kinds = [k.value for k in body.kinds] if body.kinds else list(get_settings().cv_default_kinds)
    videos = {v.id: v for v in db.scalars(select(Video).where(Video.id.in_(body.video_ids))).all()}
    missing = [str(i) for i in body.video_ids if i not in videos]
    if missing:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Videos not found: {', '.join(missing)}")
    not_ready = [v.original_filename for v in videos.values() if v.status != VideoStatus.ready]
    if not_ready:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Not ready for tracking: {', '.join(not_ready)}")
    held = [
        v.original_filename
        for v in videos.values()
        if v.processing_hold in (ProcessingHold.held, ProcessingHold.rejected)
    ]
    if held:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Waiting for the admin's approval: {', '.join(held)}")
    out = []
    for vid in dict.fromkeys(body.video_ids):
        video = videos[vid]
        try:
            created = runs_service.create_runs(db, video, kinds, body.stride, user.id)
        except runs_service.RunRequestError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
        out += [_summary(r, video.original_filename, None) for r in created]
    return out


@router.get("/runs", response_model=Page[CvRunSummary])
def list_runs(
    db: DbSession,
    _: CurrentUser,
    video_id: uuid.UUID | None = None,
    kind: Annotated[list[CvRunKind] | None, Query()] = None,
    status_: Annotated[list[CvRunStatus] | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[CvRunSummary]:
    stmt = select(CvRun, Video.original_filename, ModelVersion).join(Video, Video.id == CvRun.video_id)
    stmt = stmt.outerjoin(ModelVersion, ModelVersion.id == CvRun.model_version_id)
    if video_id:
        stmt = stmt.where(CvRun.video_id == video_id)
    if kind:
        stmt = stmt.where(CvRun.kind.in_([k.value for k in kind]))
    if status_:
        stmt = stmt.where(CvRun.status.in_(status_))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(stmt.order_by(CvRun.created_at.desc(), CvRun.id).limit(limit).offset(offset)).all()
    return Page[CvRunSummary](
        items=[_summary(r, n, mv) for r, n, mv in rows], total=total, limit=limit, offset=offset
    )


@router.get("/runs/{run_id}", response_model=CvRunDetail)
def get_run(run_id: uuid.UUID, db: DbSession, _: CurrentUser) -> CvRunDetail:
    run, name, mv = _get(db, run_id)
    tracks = db.scalars(
        select(HandTrack).where(HandTrack.run_id == run_id).order_by(HandTrack.track_id)
    ).all()
    objects = db.scalars(
        select(ObjectTrack).where(ObjectTrack.run_id == run_id).order_by(ObjectTrack.track_id)
    ).all()
    return CvRunDetail(
        **_summary(run, name, mv).model_dump(),
        config=run.config,
        stats=run.stats or {},
        output_rows=(run.output or {}).get("rows", {}),
        hand_tracks=[HandTrackRead.model_validate(t) for t in tracks],
        object_tracks=[ObjectTrackRead.model_validate(t) for t in objects],
    )


def _window(run: CvRun, frame_from: int, frame_to: int | None) -> tuple[int, int]:
    last = max(0, (run.frames_total or 1) - 1)
    hi = min(last, frame_to if frame_to is not None else last)
    if hi < frame_from:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "frame_to must be at or after frame_from")
    return frame_from, hi


def _succeeded(run: CvRun, kind: CvRunKind) -> None:
    if run.kind != kind.value:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"This is a {run.kind} run, not {kind.value}"
        )
    if run.status != CvRunStatus.succeeded:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Run is {run.status.value}; output is written when it succeeds"
        )


def _frame_window(run: CvRun, frame_from: int, frame_to: int | None) -> tuple[int, int]:
    lo, hi = _window(run, frame_from, frame_to if frame_to is not None else frame_from + MAX_FRAME_WINDOW - 1)
    if hi - lo + 1 > MAX_FRAME_WINDOW:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"Request at most {MAX_FRAME_WINDOW} frames"
        )
    return lo, hi


@router.get("/runs/{run_id}/frames", response_model=RunFrames)
def run_frames(
    run_id: uuid.UUID,
    db: DbSession,
    _: CurrentUser,
    frame_from: Annotated[int, Query(ge=0)] = 0,
    frame_to: Annotated[int | None, Query(ge=0)] = None,
) -> RunFrames:
    """Smoothed keypoints per frame, for skeleton overlays. At most 1,800 frames per request."""
    run, _, _ = _get(db, run_id)
    _succeeded(run, CvRunKind.hand_tracking)
    lo, hi = _frame_window(run, frame_from, frame_to)
    hands = store.read_window(run.output, "hands", lo, hi,
                              ["frame", "timestamp_s", "track_id", "handedness", "confidence",
                               "bbox_x", "bbox_y", "bbox_w", "bbox_h", "kp_x", "kp_y"]).to_pylist()  # fmt: skip
    fingers = store.read_window(run.output, "fingers", lo, hi,
                                ["frame", "track_id", "finger", "visibility", "occluded"]).to_pylist()  # fmt: skip
    by_hand: dict[tuple[int, int], list[FingerState]] = {}
    for f in fingers:
        by_hand.setdefault((f["frame"], f["track_id"]), []).append(
            FingerState(finger=f["finger"], visibility=f["visibility"], occluded=f["occluded"])
        )
    frames: dict[int, FrameHands] = {}
    for h in sorted(hands, key=lambda r: (r["frame"], r["track_id"])):
        fh = frames.setdefault(
            h["frame"], FrameHands(frame=h["frame"], timestamp_s=h["timestamp_s"], hands=[])
        )
        fh.hands.append(
            HandInFrame(
                track_id=h["track_id"],
                handedness=h["handedness"],
                confidence=h["confidence"],
                bbox=(h["bbox_x"], h["bbox_y"], h["bbox_w"], h["bbox_h"]),
                keypoints=list(zip(h["kp_x"], h["kp_y"], strict=True)),
                fingers=by_hand.get((h["frame"], h["track_id"]), []),
            )  # fmt: skip
        )
    return RunFrames(run_id=run.id, model_version_id=run.model_version_id, frame_from=lo, frame_to=hi,
                     frames=list(frames.values()))  # fmt: skip


def _bucket(
    frames: np.ndarray, times: np.ndarray, values: np.ndarray, lo: int, hi: int, n: int
) -> list[SeriesPoint]:
    if frames.size == 0:
        return []
    span = hi - lo + 1
    n = min(n, span)
    idx = np.minimum(((frames - lo) * n) // span, n - 1)
    order = np.argsort(idx, kind="stable")
    idx, frames, times, values = idx[order], frames[order], times[order], values[order]
    cuts = np.flatnonzero(np.diff(idx)) + 1
    points = []
    for f, t, v in zip(np.split(frames, cuts), np.split(times, cuts), np.split(values, cuts), strict=True):
        points.append(SeriesPoint(frame_start=int(f.min()), frame_end=int(f.max()), t=float(t.min()),
                                  mean=float(v.mean()), min=float(v.min()), max=float(v.max()), n=int(v.size)))  # fmt: skip
    return points


@router.get("/runs/{run_id}/series", response_model=RunSeries)
def run_series(
    run_id: uuid.UUID,
    db: DbSession,
    _: CurrentUser,
    track_id: int,
    metric: SeriesMetric = "speed",
    frame_from: Annotated[int, Query(ge=0)] = 0,
    frame_to: Annotated[int | None, Query(ge=0)] = None,
    buckets: Annotated[int, Query(ge=10, le=2000)] = 400,
) -> RunSeries:
    """Per-finger (and wrist) time series for one track, reduced to `buckets` points (mean, min, max each)."""
    run, _, _ = _get(db, run_id)
    _succeeded(run, CvRunKind.hand_tracking)
    lo, hi = _window(run, frame_from, frame_to)
    column = {"speed": "tip_speed_px_s", "accel": "tip_accel_px_s2", "visibility": "visibility"}[metric]
    table = store.read_window(
        run.output, "fingers", lo, hi, ["frame", "timestamp_s", "track_id", "finger", column]
    )
    rows = table.to_pydict()
    frames = np.asarray(rows["frame"], dtype=np.int64)
    keep = np.asarray(rows["track_id"]) == track_id
    series = []
    if metric in ("speed", "accel"):
        wcol = {"speed": "wrist_speed_px_s", "accel": "wrist_accel_px_s2"}[metric]
        w = store.read_window(
            run.output, "hands", lo, hi, ["frame", "timestamp_s", "track_id", wcol]
        ).to_pydict()
        wk = np.asarray(w["track_id"]) == track_id
        series.append(Series(name="wrist", points=_bucket(np.asarray(w["frame"])[wk], np.asarray(w["timestamp_s"])[wk],
                                                          np.asarray(w[wcol], dtype=float)[wk], lo, hi, buckets)))  # fmt: skip
    names = np.asarray(rows["finger"])
    for finger in FINGER_NAMES:
        m = keep & (names == finger)
        series.append(Series(name=finger, points=_bucket(frames[m], np.asarray(rows["timestamp_s"])[m],
                                                         np.asarray(rows[column], dtype=float)[m], lo, hi, buckets)))  # fmt: skip
    unit = {"speed": "px/s", "accel": "px/s²", "visibility": "fraction of joints in frame"}[metric]
    return RunSeries(run_id=run.id, track_id=track_id, metric=metric, unit=unit, frame_from=lo, frame_to=hi,
                     series=series)  # fmt: skip


@router.get("/runs/{run_id}/objects", response_model=RunObjects)
def run_objects(
    run_id: uuid.UUID,
    db: DbSession,
    _: CurrentUser,
    frame_from: Annotated[int, Query(ge=0)] = 0,
    frame_to: Annotated[int | None, Query(ge=0)] = None,
) -> RunObjects:
    """Tracked object boxes per frame of an object-detection run, for overlays. At most 1,800 frames."""
    run, _, _ = _get(db, run_id)
    _succeeded(run, CvRunKind.object_detection)
    lo, hi = _frame_window(run, frame_from, frame_to)
    frames: dict[int, FrameObjects] = {}
    rows = store.read_window(run.output, "objects", lo, hi).to_pylist()
    for o in sorted(rows, key=lambda r: (r["frame"], r["track_id"])):
        fo = frames.setdefault(
            o["frame"], FrameObjects(frame=o["frame"], timestamp_s=o["timestamp_s"], objects=[])
        )
        fo.objects.append(ObjectInFrame(track_id=o["track_id"], label=o["label"], score=o["score"],
                                        bbox=(o["bbox_x"], o["bbox_y"], o["bbox_w"], o["bbox_h"])))  # fmt: skip
    return RunObjects(run_id=run.id, model_version_id=run.model_version_id, frame_from=lo, frame_to=hi,
                      frames=list(frames.values()))  # fmt: skip
