import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import case, func, select
from sqlalchemy.orm import selectinload

from egolabs import annotations as service
from egolabs.api.deps import CurrentUser, DbSession, Writer
from egolabs.models import (
    Annotation,
    AnnotationCategory,
    AnnotationRevision,
    AnnotationSource,
    AnnotationType,
    User,
    Video,
)
from egolabs.schemas import Page
from egolabs.schemas.annotation import (
    AdjacentEvent,
    AnnotationCreate,
    AnnotationHistory,
    AnnotationRead,
    AnnotationUpdate,
    LabelCount,
    RevisionRead,
    TimelineBucket,
    TimelineRead,
    TimelineSegment,
    TimelineTrack,
    UserRef,
)

router = APIRouter(tags=["annotations"])


def user_ref(user: User | None) -> UserRef | None:
    return UserRef(id=user.id, name=user.name or user.email) if user else None


def read(a: Annotation) -> AnnotationRead:
    fields = {f: getattr(a, f) for f in AnnotationRead.model_fields if f != "author"}
    return AnnotationRead(**fields, author=user_ref(a.author))


def _video(db: DbSession, video_id: uuid.UUID) -> Video:
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Video not found")
    return video


def _load(db: DbSession, annotation_id: uuid.UUID) -> Annotation:
    a = db.get(Annotation, annotation_id, options=[selectinload(Annotation.author)], populate_existing=True)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Annotation not found")
    return a


# --- per video -------------------------------------------------------------------------------------


@router.get("/videos/{video_id}/annotations", response_model=Page[AnnotationRead])
def list_annotations(
    video_id: uuid.UUID,
    db: DbSession,
    _: CurrentUser,
    frame_from: Annotated[int | None, Query(ge=0, description="Overlapping this range (inclusive)")] = None,
    frame_to: Annotated[int | None, Query(ge=0)] = None,
    type_: Annotated[list[AnnotationType] | None, Query(alias="type")] = None,
    source: Annotated[list[AnnotationSource] | None, Query()] = None,
    category: AnnotationCategory | None = None,
    needs_review: bool | None = None,
    q: Annotated[str | None, Query(max_length=200, description="Label contains")] = None,
    include_deleted: bool = False,
    include_superseded: bool = False,
    deleted_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[AnnotationRead]:
    _video(db, video_id)
    stmt = select(Annotation).where(Annotation.video_id == video_id)
    if frame_from is not None:
        stmt = stmt.where(Annotation.frame_end >= frame_from)
    if frame_to is not None:
        stmt = stmt.where(Annotation.frame_start <= frame_to)
    if type_:
        stmt = stmt.where(Annotation.type.in_(type_))
    if source:
        stmt = stmt.where(Annotation.source.in_(source))
    if category:
        stmt = stmt.where(Annotation.category == category)
    if needs_review is not None:
        stmt = stmt.where(Annotation.needs_review.is_(needs_review))
    if q:
        stmt = stmt.where(Annotation.label.ilike(f"%{q}%"))
    if deleted_only:
        stmt = stmt.where(Annotation.deleted_at.is_not(None))
    elif not include_deleted:
        stmt = stmt.where(Annotation.deleted_at.is_(None))
    if not include_superseded and not deleted_only:
        stmt = stmt.where(Annotation.superseded_at.is_(None), service.from_current_runs())
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.options(selectinload(Annotation.author))
        .order_by(Annotation.frame_start, Annotation.frame_end, Annotation.created_at, Annotation.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return Page[AnnotationRead](items=[read(a) for a in rows], total=total, limit=limit, offset=offset)


@router.post("/videos/{video_id}/annotations", response_model=AnnotationRead, status_code=201)
def create_annotation(
    video_id: uuid.UUID, body: AnnotationCreate, db: DbSession, user: Writer
) -> AnnotationRead:
    video = _video(db, video_id)
    a = service.create(db, video, body, user)
    db.commit()
    return read(_load(db, a.id))


@router.get("/videos/{video_id}/annotations/adjacent", response_model=AdjacentEvent)
def adjacent_annotation(
    video_id: uuid.UUID,
    db: DbSession,
    _: CurrentUser,
    frame: Annotated[int, Query(ge=0)],
    direction: Literal["next", "prev"] = "next",
) -> AdjacentEvent:
    """Nearest annotation start after (or before) `frame`, for Shift+←/→ in the inspector."""
    _video(db, video_id)
    stmt = select(Annotation.frame_start, Annotation.id).where(
        Annotation.video_id == video_id, service.active()
    )
    if direction == "next":
        stmt = stmt.where(Annotation.frame_start > frame).order_by(Annotation.frame_start, Annotation.id)
    else:
        stmt = stmt.where(Annotation.frame_start < frame).order_by(
            Annotation.frame_start.desc(), Annotation.id
        )
    row = db.execute(stmt.limit(1)).first()
    return AdjacentEvent(frame=row[0] if row else None, annotation_id=row[1] if row else None)


# Timeline tracks, in the spec's order. `phase` is the build phase that will start filling a track that
# nothing produces yet (None once something does).
TRACKS: list[tuple[str, str, Literal["human", "ai", "event"], int | None]] = [
    ("hand", "Hand detections", "ai", None),  # hand tracking runs (Phase 3)
    ("finger", "Finger activity", "ai", None),
    ("object", "Object interactions", "ai", None),  # hand–object contact (Phase 4)
    ("movement", "Movement events", "ai", None),  # movement classification (Phase 4)
    ("human", "Human annotations", "human", None),
    ("ai", "AI annotations", "ai", 5),
    ("pipeline", "Pipeline events", "event", 7),
]

# Human work (including corrections of AI output) is one track; AI output is split by category.
_track = case(
    (Annotation.source != AnnotationSource.auto, "human"),
    (Annotation.category == AnnotationCategory.general, "ai"),
    else_=Annotation.category,
)


@router.get("/videos/{video_id}/timeline", response_model=TimelineRead)
def timeline(
    video_id: uuid.UUID,
    db: DbSession,
    _: CurrentUser,
    frame_from: Annotated[int, Query(ge=0)] = 0,
    frame_to: Annotated[int | None, Query(ge=0)] = None,
    buckets: Annotated[int, Query(ge=1, le=2000)] = 300,
    segment_limit: Annotated[int, Query(ge=1, le=1000)] = 400,
) -> TimelineRead:
    """
    What the timeline draws for a frame window. A track with at most `segment_limit` annotations in the
    window returns them all; a busier one returns counts per bucket instead, so a 30-minute video with
    per-frame detections still loads in one small response.
    """
    video = _video(db, video_id)
    last = max(0, (video.frame_count or 1) - 1)
    lo = frame_from
    hi = min(frame_to if frame_to is not None else last, last) if video.frame_count else (frame_to or last)
    if hi < lo:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "frame_to must be at or after frame_from")
    in_range = (
        (Annotation.video_id == video_id)
        & service.active()
        & (Annotation.frame_start <= hi)
        & (Annotation.frame_end >= lo)
    )
    track = _track.label("track")
    counts = dict(db.execute(select(track, func.count()).where(in_range).group_by(track)).tuples().all())

    span = hi - lo + 1
    tracks: list[TimelineTrack] = []
    for track_id, label, kind, phase in TRACKS:
        total = int(counts.get(track_id, 0))
        segments = bucket_rows = None
        if total and total <= segment_limit:
            rows = db.scalars(
                select(Annotation)
                .where(in_range, _track == track_id)
                .order_by(Annotation.frame_start, Annotation.id)
                .limit(segment_limit)
            ).all()
            segments = [
                TimelineSegment(id=a.id, start=a.frame_start, end=a.frame_end, label=a.label, type=a.type,
                                source=a.source, confidence=a.confidence, needs_review=a.needs_review)
                for a in rows
            ]  # fmt: skip
        elif total:
            n = min(buckets, span)
            index = func.floor((func.greatest(Annotation.frame_start, lo) - lo) * n / span).label("b")
            grouped = db.execute(
                select(index, func.count())
                .where(in_range, _track == track_id)
                .group_by(index)
                .order_by(index)
            ).all()
            bucket_rows = [
                TimelineBucket(
                    start=lo + (int(b) * span) // n, end=lo + ((int(b) + 1) * span) // n - 1, count=int(c)
                )
                for b, c in grouped
            ]
        else:
            segments = []
        tracks.append(
            TimelineTrack(
                id=track_id,
                label=label,
                kind=kind,
                total=total,
                segments=segments,  # type: ignore[arg-type]
                buckets=bucket_rows,
                filled_from_phase=phase,
            )  # fmt: skip
        )
    return TimelineRead(frame_from=lo, frame_to=hi, tracks=tracks)


# --- single annotation -----------------------------------------------------------------------------


@router.get("/annotations/labels", response_model=list[LabelCount])
def labels(
    db: DbSession,
    _: CurrentUser,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[LabelCount]:
    """Labels already in use, most used first, for autocomplete."""
    stmt = select(Annotation.label, func.count()).where(service.active())
    if q:
        stmt = stmt.where(Annotation.label.ilike(f"%{q}%"))
    rows = db.execute(
        stmt.group_by(Annotation.label).order_by(func.count().desc(), Annotation.label).limit(limit)
    ).all()
    return [LabelCount(label=label, count=count) for label, count in rows]


@router.get("/annotations/{annotation_id}", response_model=AnnotationRead)
def get_annotation(annotation_id: uuid.UUID, db: DbSession, _: CurrentUser) -> AnnotationRead:
    return read(_load(db, annotation_id))


@router.patch("/annotations/{annotation_id}", response_model=AnnotationRead)
def update_annotation(
    annotation_id: uuid.UUID, body: AnnotationUpdate, db: DbSession, user: Writer
) -> AnnotationRead:
    """
    Edit an annotation. Editing an AI annotation's content returns a new `auto_corrected` annotation
    (the prediction is kept, marked superseded); everything else is edited in place.
    """
    a = service.update(db, annotation_id, body, user)
    db.commit()
    return read(_load(db, a.id))


@router.delete("/annotations/{annotation_id}", response_model=AnnotationRead)
def delete_annotation(annotation_id: uuid.UUID, db: DbSession, user: Writer) -> AnnotationRead:
    """Soft delete: the annotation leaves the timeline but stays in the database with its history."""
    service.delete(db, annotation_id, user)
    db.commit()
    return read(_load(db, annotation_id))


@router.post("/annotations/{annotation_id}/restore", response_model=AnnotationRead)
def restore_annotation(annotation_id: uuid.UUID, db: DbSession, user: Writer) -> AnnotationRead:
    service.restore(db, annotation_id, user)
    db.commit()
    return read(_load(db, annotation_id))


@router.get("/annotations/{annotation_id}/history", response_model=AnnotationHistory)
def annotation_history(annotation_id: uuid.UUID, db: DbSession, _: CurrentUser) -> AnnotationHistory:
    a = _load(db, annotation_id)
    revisions = db.scalars(
        select(AnnotationRevision)
        .where(AnnotationRevision.annotation_id == annotation_id)
        .options(selectinload(AnnotationRevision.actor))
        .order_by(AnnotationRevision.revision)
    ).all()
    parent = _load(db, a.parent_annotation_id) if a.parent_annotation_id else None
    corrections = db.scalars(
        select(Annotation)
        .where(Annotation.parent_annotation_id == annotation_id)
        .options(selectinload(Annotation.author))
        .order_by(Annotation.created_at)
    ).all()
    return AnnotationHistory(
        annotation=read(a),
        revisions=[
            RevisionRead(
                revision=r.revision,
                action=r.action,
                changes=r.changes,
                snapshot=r.snapshot,
                actor=user_ref(r.actor),
                related_annotation_id=r.related_annotation_id,
                created_at=r.created_at,
            )
            for r in revisions
        ],  # fmt: skip
        parent=read(parent) if parent else None,
        corrections=[read(c) for c in corrections],
    )
