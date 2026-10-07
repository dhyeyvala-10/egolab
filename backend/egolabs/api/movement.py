"""
Movement classes, movement events, their evidence, and the interaction graph (spec Phase 4).

Events are listed from each video's latest classification run by default (`current=true`), like the
timeline; older runs' events stay in the database for comparison.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import Select, func, select
from sqlalchemy.orm import selectinload

from egolabs import annotations as annotation_service
from egolabs import review
from egolabs.api.annotations import read as read_annotation
from egolabs.api.annotations import user_ref
from egolabs.api.deps import CurrentUser, DbSession, Lead, Writer
from egolabs.cv import store
from egolabs.cv.movement import evidence
from egolabs.cv.movement.classes import BUILTIN
from egolabs.models import (
    Annotation,
    CaptureSession,
    CvRun,
    ModelVersion,
    MovementClass,
    MovementEvent,
    MovementEventStatus,
    User,
    Video,
)
from egolabs.schemas import Page
from egolabs.schemas.catalog import Ref
from egolabs.schemas.cv import ModelVersionRef
from egolabs.schemas.movement import (
    ClassRef,
    EventEvidence,
    EventEvidenceFrames,
    EvidenceFrame,
    GraphEvent,
    GraphLink,
    GraphNode,
    InteractionGraph,
    MovementClassCreate,
    MovementClassRead,
    MovementClassUpdate,
    MovementEventDetail,
    MovementEventSummary,
    MovementEventUpdate,
)

router = APIRouter(prefix="/movement", tags=["movement"])

MAX_EVIDENCE_FRAMES = 600


# --- classes ---------------------------------------------------------------------------------------


def _class_counts(db: DbSession) -> dict[uuid.UUID, int]:
    rows = db.execute(
        select(MovementEvent.class_id, func.count())
        .where(MovementEvent.run_id.in_(annotation_service.latest_runs()))
        .group_by(MovementEvent.class_id)
    ).all()
    return {cid: n for cid, n in rows}


def _class_read(c: MovementClass, counts: dict[uuid.UUID, int]) -> MovementClassRead:
    return MovementClassRead.model_validate({**{k: getattr(c, k) for k in MovementClassRead.model_fields
                                                 if k != "events"}, "events": counts.get(c.id, 0)})  # fmt: skip


@router.get("/classes", response_model=list[MovementClassRead])
def list_classes(db: DbSession, _: CurrentUser) -> list[MovementClassRead]:
    """Every movement class: the spec's built-ins first (in the spec's order), then custom classes."""
    counts = _class_counts(db)
    spec = {name: i for i, (name, *_) in enumerate(BUILTIN)}
    rows = sorted(db.scalars(select(MovementClass)).all(),
                  key=lambda c: (spec.get(c.name, len(spec)) if c.builtin else len(spec), c.created_at, c.name))  # fmt: skip
    return [_class_read(c, counts) for c in rows]


@router.post("/classes", response_model=MovementClassRead, status_code=201)
def create_class(body: MovementClassCreate, db: DbSession, user: Lead) -> MovementClassRead:
    """Add a custom class. Annotators can label with it now; a learned classifier can emit it later."""
    if db.scalar(select(MovementClass).where(MovementClass.name == body.name)):
        raise HTTPException(status.HTTP_409_CONFLICT, f"A class named {body.name!r} already exists")
    c = MovementClass(**body.model_dump(), builtin=False, created_by=user.id)
    db.add(c)
    db.commit()
    return _class_read(c, {})


@router.patch("/classes/{class_id}", response_model=MovementClassRead)
def update_class(class_id: uuid.UUID, body: MovementClassUpdate, db: DbSession, _: Lead) -> MovementClassRead:
    """Relabel, describe, or switch a class on or off. Its `name` stays: classifiers and events use it."""
    c = db.get(MovementClass, class_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Class not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(c, k, v)
    c.updated_at = datetime.now(UTC)
    db.commit()
    return _class_read(c, _class_counts(db))


# --- events ----------------------------------------------------------------------------------------


def _events_query(
    *,
    current: bool,
    video_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
    class_: list[str] | None = None,
    status_: list[MovementEventStatus] | None = None,
    handedness: str | None = None,
    finger: str | None = None,
    object_label: str | None = None,
    min_confidence: float | None = None,
    max_confidence: float | None = None,
) -> Select:
    stmt = select(MovementEvent).join(MovementClass, MovementClass.id == MovementEvent.class_id)
    if current and run_id is None:  # each video's latest run, with corrections in place of what they correct
        stmt = stmt.where(
            MovementEvent.run_id.in_(annotation_service.latest_runs()), MovementEvent.superseded_at.is_(None)
        )
    if run_id:
        stmt = stmt.where(MovementEvent.run_id == run_id)
    if video_id:
        stmt = stmt.where(MovementEvent.video_id == video_id)
    if session_id:
        stmt = stmt.where(MovementEvent.session_id == session_id)
    if class_:
        stmt = stmt.where(MovementClass.name.in_(class_))
    if status_:
        stmt = stmt.where(MovementEvent.status.in_(status_))
    if handedness:
        stmt = stmt.where(MovementEvent.handedness == handedness)
    if finger:
        stmt = stmt.where(MovementEvent.fingers.contains([finger]))
    if object_label:
        stmt = stmt.where(MovementEvent.object_label == object_label)
    if min_confidence is not None:
        stmt = stmt.where(MovementEvent.confidence >= min_confidence)
    if max_confidence is not None:
        stmt = stmt.where(MovementEvent.confidence <= max_confidence)
    return stmt


def _summaries(db: DbSession, events: list[MovementEvent]) -> list[MovementEventSummary]:
    if not events:
        return []
    classes = {
        c.id: c
        for c in db.scalars(select(MovementClass).where(MovementClass.id.in_({e.class_id for e in events})))
    }
    videos = dict(db.execute(select(Video.id, Video.original_filename).where(Video.id.in_({e.video_id for e in events}))).tuples().all())  # fmt: skip
    sids = {e.session_id for e in events if e.session_id}
    sessions = dict(db.execute(select(CaptureSession.id, CaptureSession.name).where(CaptureSession.id.in_(sids))).tuples().all()) if sids else {}  # fmt: skip
    mvs = {m.id: m for m in db.scalars(select(ModelVersion).where(ModelVersion.id.in_({e.model_version_id for e in events})))}  # fmt: skip
    labels = dict(db.execute(select(Annotation.id, Annotation.label).where(Annotation.id.in_({e.annotation_id for e in events}))).tuples().all())  # fmt: skip
    out = []
    for e in events:
        c = classes[e.class_id]
        out.append(MovementEventSummary(
            id=e.id, video=Ref(id=e.video_id, name=videos.get(e.video_id, "")),
            session=Ref(id=e.session_id, name=sessions.get(e.session_id, "")) if e.session_id else None,
            movement_class=ClassRef(id=c.id, name=c.name, label=c.label), label=labels.get(e.annotation_id, c.label),
            start_frame=e.start_frame, end_frame=e.end_frame, start_s=e.start_s, end_s=e.end_s,
            handedness=e.handedness, hand_track_id=e.hand_track_id, fingers=list(e.fingers),
            object_track_id=e.object_track_id, object_label=e.object_label, confidence=e.confidence, status=e.status,
            source=e.source.value, parent_event_id=e.parent_event_id, superseded_at=e.superseded_at,
            review_method=e.review_method.value if e.review_method else None,
            model_version=ModelVersionRef.model_validate(mvs[e.model_version_id]), run_id=e.run_id,
            hand_run_id=e.hand_run_id, object_run_id=e.object_run_id, annotation_id=e.annotation_id,
            attributes=e.attributes or {}, created_at=e.created_at,
        ))  # fmt: skip
    return out


EventSort = Literal["start", "-start", "confidence", "-confidence", "created", "-created"]
_SORTS = {
    "start": (MovementEvent.video_id, MovementEvent.start_frame, MovementEvent.end_frame),
    "confidence": (MovementEvent.confidence,),
    "created": (MovementEvent.created_at,),
}


@router.get("/events", response_model=Page[MovementEventSummary])
def list_events(
    db: DbSession,
    _: CurrentUser,
    video_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    run_id: Annotated[
        uuid.UUID | None, Query(description="One classification run (implies current=false)")
    ] = None,
    class_: Annotated[list[str] | None, Query(alias="class", description="Class names")] = None,
    status_: Annotated[list[MovementEventStatus] | None, Query(alias="status")] = None,
    handedness: Literal["left", "right"] | None = None,
    finger: Literal["thumb", "index", "middle", "ring", "pinky"] | None = None,
    object_label: Annotated[str | None, Query(max_length=100)] = None,
    min_confidence: Annotated[float | None, Query(ge=0, le=1)] = None,
    max_confidence: Annotated[float | None, Query(ge=0, le=1)] = None,
    current: Annotated[bool, Query(description="Only each video's latest classification run")] = True,
    sort: EventSort = "start",
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[MovementEventSummary]:
    stmt = _events_query(current=current, video_id=video_id, session_id=session_id, run_id=run_id, class_=class_,
                         status_=status_, handedness=handedness, finger=finger, object_label=object_label,
                         min_confidence=min_confidence, max_confidence=max_confidence)  # fmt: skip
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    cols = _SORTS[sort.lstrip("-")]
    order = [c.desc() for c in cols] if sort.startswith("-") else list(cols)
    rows = db.scalars(stmt.order_by(*order, MovementEvent.id).limit(limit).offset(offset)).all()
    return Page[MovementEventSummary](
        items=_summaries(db, list(rows)), total=total, limit=limit, offset=offset
    )


def _event(db: DbSession, event_id: uuid.UUID) -> MovementEvent:
    e = db.get(MovementEvent, event_id)
    if e is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")
    return e


def _detail(db: DbSession, e: MovementEvent) -> MovementEventDetail:
    ann = db.get(
        Annotation, e.annotation_id, options=[selectinload(Annotation.author)], populate_existing=True
    )
    assert ann is not None
    ev = e.evidence or {}
    kp = ev.get("keypoints", {})
    reviewer = db.get(User, e.reviewed_by) if e.reviewed_by else None
    return MovementEventDetail(
        **_summaries(db, [e])[0].model_dump(),
        evidence=EventEvidence(frames=evidence.decode(ev.get("frames", [])), frame_count=ev.get("frame_count", 0),
                               measurements=ev.get("measurements", {}), thresholds=ev.get("thresholds", {}),
                               rule=ev.get("rule", ""), hand_run_id=e.hand_run_id,
                               track_id=kp.get("track_id", e.hand_track_id), parts=kp.get("parts", [])),
        annotation=read_annotation(ann), reviewed_by=user_ref(reviewer), reviewed_at=e.reviewed_at,
    )  # fmt: skip


@router.get("/events/{event_id}", response_model=MovementEventDetail)
def get_event(event_id: uuid.UUID, db: DbSession, _: CurrentUser) -> MovementEventDetail:
    return _detail(db, _event(db, event_id))


@router.get("/events/{event_id}/evidence", response_model=EventEvidenceFrames)
def event_evidence(
    event_id: uuid.UUID,
    db: DbSession,
    _: CurrentUser,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_EVIDENCE_FRAMES)] = 300,
) -> EventEvidenceFrames:
    """
    The exact keypoint frames that produced the event, read back from the hand-tracking run's Parquet files,
    with the rule's measurement for each frame and the event's object box where it was detected.
    """
    e = _event(db, event_id)
    ev = e.evidence or {}
    frames = evidence.decode(ev.get("frames", []))
    page = frames[offset : offset + limit]
    hand_run = db.get(CvRun, e.hand_run_id)
    assert hand_run is not None
    index = {f: i for i, f in enumerate(frames)}
    measurements = ev.get("measurements", {})
    out: list[EvidenceFrame] = []
    if page:
        lo, hi = page[0], page[-1]
        wanted = set(page)
        rows = store.read_window(hand_run.output, "hands", lo, hi,
                                 ["frame", "timestamp_s", "track_id", "handedness", "confidence",
                                  "bbox_x", "bbox_y", "bbox_w", "bbox_h", "kp_x", "kp_y"]).to_pylist()  # fmt: skip
        boxes: dict[int, tuple[float, float, float, float]] = {}
        if e.object_run_id and e.object_track_id is not None:
            obj_run = db.get(CvRun, e.object_run_id)
            if obj_run is not None:
                for o in store.read_window(obj_run.output, "objects", lo, hi).to_pylist():
                    if o["track_id"] == e.object_track_id:
                        boxes[o["frame"]] = (o["bbox_x"], o["bbox_y"], o["bbox_w"], o["bbox_h"])
        for r in sorted(rows, key=lambda r: r["frame"]):
            if r["track_id"] != e.hand_track_id or r["frame"] not in wanted:
                continue
            i = index[r["frame"]]
            out.append(EvidenceFrame(
                frame=r["frame"], timestamp_s=r["timestamp_s"], confidence=r["confidence"], handedness=r["handedness"],
                keypoints=list(zip(r["kp_x"], r["kp_y"], strict=True)),
                bbox=(r["bbox_x"], r["bbox_y"], r["bbox_w"], r["bbox_h"]), object_bbox=boxes.get(r["frame"]),
                values={k: v[i] for k, v in measurements.items() if i < len(v)},
            ))  # fmt: skip
    return EventEvidenceFrames(event_id=e.id, hand_run_id=e.hand_run_id, model_version_id=hand_run.model_version_id,
                               track_id=e.hand_track_id, total=len(frames), offset=offset, limit=limit, frames=out)  # fmt: skip


@router.patch("/events/{event_id}", response_model=MovementEventDetail)
def review_event(
    event_id: uuid.UUID, body: MovementEventUpdate, db: DbSession, user: Writer
) -> MovementEventDetail:
    """
    Confirm, reject, or flag an event. Rejecting takes its segment off the timeline (a soft delete, kept in
    history); confirming clears the review flag. To correct an event, use `POST /review/events/{id}/correct`
    (or edit its segment in the inspector): corrections are new event versions.
    """
    e = db.get(MovementEvent, event_id, with_for_update=True)
    if e is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")
    try:
        review.set_status(db, e, MovementEventStatus(body.status), user)
    except review.ReviewError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    db.commit()
    return _detail(db, e)


# --- interaction graph -----------------------------------------------------------------------------

FINGER_ORDER = ("thumb", "index", "middle", "ring", "pinky")


@router.get("/graph", response_model=InteractionGraph)
def interaction_graph(
    db: DbSession,
    _: CurrentUser,
    video_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    class_: Annotated[list[str] | None, Query(alias="class")] = None,
    min_confidence: Annotated[float | None, Query(ge=0, le=1)] = None,
    include_rejected: bool = False,
    limit: Annotated[int, Query(ge=1, le=2000, description="Events returned with their paths")] = 500,
) -> InteractionGraph:
    """
    Hand → Finger(s) → Movement → Object → Time range over the current events: node and link counts over
    all matching events, plus each event's path and time range (the first `limit` in time order).
    """
    if video_id is None and session_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Give a video_id or session_id")
    stmt = _events_query(current=True, video_id=video_id, session_id=session_id, class_=class_,
                         min_confidence=min_confidence)  # fmt: skip
    if not include_rejected:
        stmt = stmt.where(MovementEvent.status != MovementEventStatus.rejected)
    stmt = stmt.add_columns(MovementClass.name, MovementClass.label)
    nodes: dict[str, GraphNode] = {}
    links: dict[tuple[str, str], int] = {}
    events: list[GraphEvent] = []
    total = 0
    order = (MovementEvent.video_id, MovementEvent.start_frame, MovementEvent.end_frame, MovementEvent.id)
    for e, cname, clabel in db.execute(stmt.order_by(*order).execution_options(yield_per=1000)):
        total += 1
        hand = f"hand:{e.handedness}"
        fingers = [f"finger:{f}" for f in FINGER_ORDER if f in e.fingers] or ["finger:whole_hand"]
        move = f"movement:{cname}"
        obj = f"object:{e.object_label}" if e.object_label else "object:none"
        for nid, kind, label in (
            (hand, "hand", f"{e.handedness.capitalize()} hand"),
            *((f, "finger", f.split(":")[1].replace("_", " ").capitalize()) for f in fingers),
            (move, "movement", clabel),
            (obj, "object", e.object_label or "No object"),
        ):
            n = nodes.setdefault(nid, GraphNode(id=nid, kind=kind, label=label, count=0))  # type: ignore[arg-type]
            n.count += 1
        for f in fingers:
            links[(hand, f)] = links.get((hand, f), 0) + 1
            links[(f, move)] = links.get((f, move), 0) + 1
        links[(move, obj)] = links.get((move, obj), 0) + 1
        if len(events) < limit:
            events.append(GraphEvent(id=e.id, video_id=e.video_id, path=[hand, *fingers, move, obj], label=clabel,
                                     start_frame=e.start_frame, end_frame=e.end_frame, start_s=e.start_s,
                                     end_s=e.end_s, confidence=e.confidence, status=e.status))  # fmt: skip
    kinds = {"hand": 0, "finger": 1, "movement": 2, "object": 3}
    return InteractionGraph(
        nodes=sorted(nodes.values(), key=lambda n: (kinds[n.kind], -n.count, n.label)),
        links=[
            GraphLink(source=s, target=t, count=c)
            for (s, t), c in sorted(links.items(), key=lambda kv: -kv[1])
        ],
        events=events,
        total_events=total,
    )
