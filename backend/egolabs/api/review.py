"""
Review and active learning (spec Phase 5): the review queue, per-class and per-object summaries, review and
correction of events, bulk review with undo, auto-accept rules, review metrics, and auto annotation.

Everything reads each video's latest classification run, with corrections in place of the predictions they
replace (older runs and superseded predictions stay in the database).
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import Select, case, func, or_, select
from sqlalchemy.orm import Session

from egolabs import annotations as annotation_service
from egolabs import review
from egolabs.api.annotations import user_ref
from egolabs.api.cv import _summary as run_summary
from egolabs.api.deps import CurrentUser, DbSession, Lead, Processor, Writer
from egolabs.api.movement import _detail, _summaries
from egolabs.config import get_settings
from egolabs.cv import registry
from egolabs.cv import runs as runs_service
from egolabs.cv.adapters.base import AdapterError
from egolabs.models import (
    AnnotationSource,
    CaptureSession,
    CvRun,
    CvRunKind,
    ModelVersion,
    MovementClass,
    MovementEvent,
    MovementEventReview,
    MovementEventStatus,
    ProcessingHold,
    ReviewBatch,
    ReviewMethod,
    ReviewRule,
    User,
    Video,
    VideoStatus,
)
from egolabs.schemas import Page
from egolabs.schemas.catalog import Ref
from egolabs.schemas.movement import ClassRef
from egolabs.schemas.review import (
    AnnotatorMetric,
    AutoAnnotateRequest,
    AutoAnnotateResult,
    BulkPreview,
    BulkRequest,
    ClassMetric,
    CorrectionCreate,
    CorrectionResult,
    DailyReviews,
    EventHistory,
    EventVersion,
    ModelVersionRead,
    PriorityParts,
    QueuePage,
    ReviewBatchRead,
    ReviewFilters,
    ReviewGroup,
    ReviewItem,
    ReviewLogEntry,
    ReviewMetrics,
    ReviewRuleCreate,
    ReviewRuleRead,
    ReviewRuleUpdate,
    ReviewStatusUpdate,
    ReviewSummary,
    RuleApplyRequest,
    SkippedVideo,
)

router = APIRouter(prefix="/review", tags=["review"])

MAX_AUTO_VIDEOS = 500


def _filters(body: ReviewFilters) -> review.Filters:
    return review.Filters(**body.model_dump())


def _event(db: Session, event_id: uuid.UUID, lock: bool = False) -> MovementEvent:
    e = db.get(MovementEvent, event_id, with_for_update=lock)
    if e is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")
    return e


def _conflict(exc: review.ReviewError) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, str(exc))


# --- queue -----------------------------------------------------------------------------------------

QueueSort = Literal["priority", "confidence", "disagreement", "rarity", "start"]


@router.get("/queue", response_model=QueuePage)
def queue(
    db: DbSession,
    _: CurrentUser,
    video_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    class_: Annotated[list[str] | None, Query(alias="class")] = None,
    object_label: Annotated[str | None, Query(max_length=100)] = None,
    no_object: bool = False,
    handedness: Literal["left", "right"] | None = None,
    status_: Annotated[
        list[MovementEventStatus] | None, Query(alias="status", description="Default: pending")
    ] = None,
    min_confidence: Annotated[float | None, Query(ge=0, le=1)] = None,
    max_confidence: Annotated[float | None, Query(ge=0, le=1)] = None,
    sort: QueueSort = "priority",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> QueuePage:
    """
    The active-learning queue: pending events, most useful to review first. `priority` combines lowest
    confidence, highest model disagreement, and rarest class (each item says how much each contributed);
    the other sorts use one of them alone.
    """
    f = review.Filters(video_id=video_id, session_id=session_id, classes=class_ or [], object_label=object_label,
                       no_object=no_object, handedness=handedness, min_confidence=min_confidence,
                       max_confidence=max_confidence)  # fmt: skip
    if status_:
        f.statuses = list(status_)
    base = review.apply_filters(select(MovementEvent), f)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    stmt, rarity, priority = review.scored(base)
    order = {
        "priority": (priority.desc(), MovementEvent.confidence.asc().nulls_last()),
        "confidence": (MovementEvent.confidence.asc().nulls_last(), priority.desc()),
        "disagreement": (MovementEvent.disagreement.desc().nulls_last(), priority.desc()),
        "rarity": (rarity.desc(), priority.desc()),
        "start": (MovementEvent.video_id, MovementEvent.start_frame),
    }[sort]
    rows = db.execute(stmt.order_by(*order, MovementEvent.id).limit(limit).offset(offset)).all()
    w = review.weights()
    summaries = _summaries(db, [r[0] for r in rows])
    items = []
    for (e, r, p), s in zip(rows, summaries, strict=True):
        parts = PriorityParts(confidence=round(w["confidence"] * (1 - (e.confidence if e.confidence is not None else 1)), 4),
                              disagreement=round(w["disagreement"] * (e.disagreement or 0.0), 4),
                              rarity=round(w["rarity"] * float(r), 4))  # fmt: skip
        items.append(ReviewItem(**s.model_dump(), disagreement=e.disagreement, compared_versions=e.compared_versions,
                                rarity=round(float(r), 4), priority=round(float(p), 4), priority_parts=parts))  # fmt: skip
    return QueuePage(items=items, total=total, limit=limit, offset=offset, weights=w)


# --- summaries (the review home's cards) -------------------------------------------------------------


def _group_counts(stmt: Select) -> Select:
    s = MovementEvent.status
    return stmt.add_columns(
        func.count().label("total"),
        func.count().filter(s.in_(review.PENDING)).label("pending"),
        func.count().filter(s == MovementEventStatus.needs_review).label("needs_review"),
        func.count().filter(s == MovementEventStatus.confirmed).label("confirmed"),
        func.count().filter(s == MovementEventStatus.confirmed, MovementEvent.review_method == ReviewMethod.auto_rule).label("auto"),
        func.count().filter(s == MovementEventStatus.rejected).label("rejected"),
        func.count().filter(s == MovementEventStatus.corrected).label("corrected"),
        func.avg(MovementEvent.confidence).label("mean"),
        func.min(MovementEvent.confidence).label("min"),
    )  # fmt: skip


def _group(key: str, label: str, cls: ClassRef | None, row) -> ReviewGroup:
    return ReviewGroup(key=key, label=label, movement_class=cls, total=row.total, pending=row.pending,
                       needs_review=row.needs_review, confirmed=row.confirmed, auto_accepted=row.auto,
                       rejected=row.rejected, corrected=row.corrected,
                       mean_confidence=round(row.mean, 4) if row.mean is not None else None,
                       min_confidence=row.min)  # fmt: skip


@router.get("/summary", response_model=ReviewSummary)
def summary(
    db: DbSession,
    _: CurrentUser,
    group: Literal["class", "object"] = "class",
    video_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    class_: Annotated[list[str] | None, Query(alias="class")] = None,
) -> ReviewSummary:
    """
    Review progress per class or per object, over each video's latest predictions (a corrected prediction
    counts as corrected; its correction isn't counted again).
    """
    base = (
        select()
        .select_from(MovementEvent)
        .where(
            MovementEvent.run_id.in_(annotation_service.latest_runs()),
            MovementEvent.source == AnnotationSource.auto,
        )
    )
    if video_id:
        base = base.where(MovementEvent.video_id == video_id)
    if session_id:
        base = base.where(MovementEvent.session_id == session_id)
    if class_:
        base = base.where(
            MovementEvent.class_id.in_(select(MovementClass.id).where(MovementClass.name.in_(class_)))
        )
    totals_row = db.execute(_group_counts(base)).one()
    groups: list[ReviewGroup] = []
    if group == "class":
        classes = {c.id: c for c in db.scalars(select(MovementClass))}
        for row in db.execute(
            _group_counts(base.add_columns(MovementEvent.class_id)).group_by(MovementEvent.class_id)
        ):
            c = classes[row.class_id]
            groups.append(_group(c.name, c.label, ClassRef(id=c.id, name=c.name, label=c.label), row))
    else:
        stmt = _group_counts(base.add_columns(MovementEvent.object_label)).group_by(
            MovementEvent.object_label
        )
        for row in db.execute(stmt):
            groups.append(_group(row.object_label or "", row.object_label or "No object", None, row))
    groups.sort(key=lambda g: (-g.pending, -g.total, g.label))
    return ReviewSummary(group=group, groups=groups, totals=_group("", "All", None, totals_row))


# --- one event -------------------------------------------------------------------------------------


@router.post("/events/{event_id}/status", response_model=CorrectionResult)
def set_status(
    event_id: uuid.UUID, body: ReviewStatusUpdate, db: DbSession, user: Writer
) -> CorrectionResult:
    """Accept (`confirmed`), reject, flag (`needs_review`), or reopen (`auto_detected`) one event."""
    e = _event(db, event_id, lock=True)
    try:
        review.set_status(db, e, MovementEventStatus(body.status), user)
    except review.ReviewError as exc:
        raise _conflict(exc) from exc
    db.commit()
    return CorrectionResult(event=_detail(db, e), parent_event_id=e.parent_event_id)


@router.post("/events/{event_id}/correct", response_model=CorrectionResult, status_code=201)
def correct(event_id: uuid.UUID, body: CorrectionCreate, db: DbSession, user: Writer) -> CorrectionResult:
    """
    Correct an event: its class, frame range, hand, fingers, or object. A prediction is never changed: the
    correction is a new event version (with its own timeline segment) whose parent is the prediction, and
    the prediction is kept, marked corrected.
    """
    e = _event(db, event_id, lock=True)
    fields = body.model_dump(exclude={"class_name"})
    try:
        version = review.correct(db, e, review.Correction(class_name=body.class_name, **fields), user)
    except review.ReviewError as exc:
        raise _conflict(exc) from exc
    db.commit()
    return CorrectionResult(event=_detail(db, version), parent_event_id=version.parent_event_id)


def _chain(db: Session, e: MovementEvent) -> list[MovementEvent]:
    root = e
    while root.parent_event_id is not None:
        parent = db.get(MovementEvent, root.parent_event_id)
        if parent is None:
            break
        root = parent
    out, frontier = [root], [root.id]
    while frontier:
        children = db.scalars(select(MovementEvent).where(MovementEvent.parent_event_id.in_(frontier))
                              .order_by(MovementEvent.created_at)).all()  # fmt: skip
        out += children
        frontier = [c.id for c in children]
    return out


@router.get("/events/{event_id}/history", response_model=EventHistory)
def history(event_id: uuid.UUID, db: DbSession, _: CurrentUser) -> EventHistory:
    """Every version of an event (the prediction, then corrections) and every review of each."""
    versions = _chain(db, _event(db, event_id))
    classes = {c.id: c for c in db.scalars(select(MovementClass).where(MovementClass.id.in_({v.class_id for v in versions})))}  # fmt: skip
    log = db.execute(
        select(MovementEventReview, User)
        .outerjoin(User, User.id == MovementEventReview.actor_id)
        .where(MovementEventReview.event_id.in_([v.id for v in versions]))
        .order_by(MovementEventReview.created_at, MovementEventReview.id)
    ).all()
    return EventHistory(
        versions=[
            EventVersion(
                id=v.id,
                source=v.source.value,
                movement_class=ClassRef(
                    id=v.class_id, name=classes[v.class_id].name, label=classes[v.class_id].label
                ),
                start_frame=v.start_frame,
                end_frame=v.end_frame,
                handedness=v.handedness,
                fingers=list(v.fingers),
                object_label=v.object_label,
                confidence=v.confidence,
                status=v.status,
                superseded_at=v.superseded_at,
                created_at=v.created_at,
                annotation_id=v.annotation_id,
            )
            for v in versions
        ],  # fmt: skip
        log=[
            ReviewLogEntry(
                id=r.id,
                event_id=r.event_id,
                from_status=r.from_status,
                to_status=r.to_status,
                method=r.method,
                actor=user_ref(u),
                batch_id=r.batch_id,
                rule_id=r.rule_id,
                related_event_id=r.related_event_id,
                created_at=r.created_at,
            )
            for r, u in log
        ],  # fmt: skip
    )


# --- bulk review -----------------------------------------------------------------------------------


def _preview(db: Session, stmt: Select) -> BulkPreview:
    count = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    limit = get_settings().review_bulk_max
    sample = db.scalars(
        stmt.order_by(MovementEvent.video_id, MovementEvent.start_frame, MovementEvent.id).limit(5)
    ).all()
    sub = stmt.subquery()
    by_class = dict(db.execute(
        select(MovementClass.name, func.count()).join(sub, MovementClass.id == sub.c.class_id).group_by(MovementClass.name)
    ).tuples().all()) if count else {}  # fmt: skip
    return BulkPreview(count=count, limit=limit, over_limit=count > limit, sample=_summaries(db, list(sample)),
                       by_class=by_class)  # fmt: skip


@router.post("/bulk/preview", response_model=BulkPreview)
def bulk_preview(body: BulkRequest, db: DbSession, _: Lead) -> BulkPreview:
    """How many pending events a bulk review would change, with a sample. Changes nothing."""
    return _preview(db, review.bulk_query(_filters(body.filters)))


def _batch_read(db: Session, b: ReviewBatch) -> ReviewBatchRead:
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_({i for i in (b.actor_id, b.undone_by) if i})))}  # fmt: skip
    return ReviewBatchRead(id=b.id, action=b.action, method=ReviewMethod(b.filters.get("method", "bulk")),
                           filters={k: v for k, v in b.filters.items() if k != "method"}, count=b.count,
                           actor=user_ref(users.get(b.actor_id)) if b.actor_id else None, created_at=b.created_at,
                           undone_at=b.undone_at, undone_by=user_ref(users.get(b.undone_by)) if b.undone_by else None,
                           undone_count=b.undone_count)  # fmt: skip


@router.post("/bulk", response_model=ReviewBatchRead, status_code=201)
def bulk(body: BulkRequest, db: DbSession, user: Lead) -> ReviewBatchRead:
    """
    Confirm or reject every pending event matching the filters, as one batch (method `bulk`). Undo it with
    `POST /review/batches/{id}/undo`.
    """
    try:
        batch = review.bulk(db, _filters(body.filters), MovementEventStatus(body.action), user)
    except review.ReviewError as exc:
        raise _conflict(exc) from exc
    db.commit()
    return _batch_read(db, batch)


@router.get("/batches", response_model=Page[ReviewBatchRead])
def list_batches(
    db: DbSession,
    _: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ReviewBatchRead]:
    total = db.scalar(select(func.count()).select_from(ReviewBatch)) or 0
    rows = db.scalars(select(ReviewBatch).order_by(ReviewBatch.created_at.desc(), ReviewBatch.id).limit(limit).offset(offset)).all()  # fmt: skip
    return Page[ReviewBatchRead](
        items=[_batch_read(db, b) for b in rows], total=total, limit=limit, offset=offset
    )


@router.post("/batches/{batch_id}/undo", response_model=ReviewBatchRead)
def undo_batch(batch_id: uuid.UUID, db: DbSession, user: Lead) -> ReviewBatchRead:
    """Put back each event the batch changed that nobody has reviewed since."""
    batch = db.get(ReviewBatch, batch_id, with_for_update=True)
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Batch not found")
    try:
        review.undo(db, batch, user)
    except review.ReviewError as exc:
        raise _conflict(exc) from exc
    db.commit()
    return _batch_read(db, batch)


# --- auto-accept rules -----------------------------------------------------------------------------


def _rule_read(db: Session, r: ReviewRule, cls: MovementClass | None) -> ReviewRuleRead:
    accepted = db.scalar(select(func.count()).select_from(MovementEvent).where(
        MovementEvent.review_rule_id == r.id, MovementEvent.status == MovementEventStatus.confirmed)) or 0  # fmt: skip
    return ReviewRuleRead(id=r.id, movement_class=ClassRef(id=cls.id, name=cls.name, label=cls.label) if cls else None,
                          min_confidence=r.min_confidence, enabled=r.enabled, created_at=r.created_at,
                          updated_at=r.updated_at, accepted=accepted)  # fmt: skip


@router.get("/rules", response_model=list[ReviewRuleRead])
def list_rules(db: DbSession, _: CurrentUser) -> list[ReviewRuleRead]:
    """Auto-accept rules: the default (no class) first, then per class."""
    classes = {c.id: c for c in db.scalars(select(MovementClass))}
    rules = sorted(db.scalars(select(ReviewRule)).all(),
                   key=lambda r: (r.class_id is not None, classes[r.class_id].label if r.class_id else ""))  # fmt: skip
    return [_rule_read(db, r, classes.get(r.class_id) if r.class_id else None) for r in rules]


@router.post("/rules", response_model=ReviewRuleRead, status_code=201)
def create_rule(body: ReviewRuleCreate, db: DbSession, user: Lead) -> ReviewRuleRead:
    """
    Add an auto-accept rule: new predictions at or above `min_confidence` are confirmed automatically
    (method `auto_rule`). With no class it is the default for every class without its own rule. It applies
    to classification runs from now on; `POST /review/rules/apply` applies the rules to pending events.
    """
    cls = None
    if body.class_name:
        cls = db.scalar(select(MovementClass).where(MovementClass.name == body.class_name))
        if cls is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, f"No movement class named {body.class_name!r}"
            )
    class_id = cls.id if cls else None
    if db.scalar(
        select(ReviewRule).where(
            ReviewRule.class_id.is_(None) if class_id is None else ReviewRule.class_id == class_id
        )
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "That class already has a rule; edit it instead")  # fmt: skip
    r = ReviewRule(
        class_id=class_id, min_confidence=body.min_confidence, enabled=body.enabled, created_by=user.id
    )
    db.add(r)
    db.commit()
    return _rule_read(db, r, cls)


def _rule(db: Session, rule_id: uuid.UUID) -> ReviewRule:
    r = db.get(ReviewRule, rule_id)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rule not found")
    return r


@router.patch("/rules/{rule_id}", response_model=ReviewRuleRead)
def update_rule(rule_id: uuid.UUID, body: ReviewRuleUpdate, db: DbSession, user: Lead) -> ReviewRuleRead:
    """Change a rule's threshold or switch it off (a class whose rule is off is never auto-accepted)."""
    r = _rule(db, rule_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(r, k, v)
    r.updated_at, r.updated_by = datetime.now(UTC), user.id
    db.commit()
    return _rule_read(db, r, db.get(MovementClass, r.class_id) if r.class_id else None)


@router.delete("/rules/{rule_id}", status_code=204)
def delete_rule(rule_id: uuid.UUID, db: DbSession, _: Lead) -> None:
    """Remove a rule (events it accepted stay confirmed, and still name it until then)."""
    db.delete(_rule(db, rule_id))
    db.commit()


@router.post("/rules/apply/preview", response_model=BulkPreview)
def rules_preview(body: RuleApplyRequest, db: DbSession, _: Lead) -> BulkPreview:
    """How many pending predictions the rules would accept now. Changes nothing."""
    return _preview(db, review.rule_candidates(db, _filters(body.filters)))


@router.post("/rules/apply", response_model=ReviewBatchRead, status_code=201)
def rules_apply(body: RuleApplyRequest, db: DbSession, user: Lead) -> ReviewBatchRead:
    """Apply the rules to pending predictions, as one undoable batch (method `auto_rule`)."""
    try:
        batch = review.bulk(
            db, _filters(body.filters), MovementEventStatus.confirmed, user, method=ReviewMethod.auto_rule
        )
    except review.ReviewError as exc:
        raise _conflict(exc) from exc
    db.commit()
    return _batch_read(db, batch)


# --- metrics ---------------------------------------------------------------------------------------


def _rate(n: int, d: int) -> float | None:
    return round(n / d, 4) if d else None


@router.get("/metrics", response_model=ReviewMetrics)
def metrics(
    db: DbSession,
    _: CurrentUser,
    days: Annotated[
        int, Query(ge=1, le=365, description="Window for annotator throughput and the daily series")
    ] = 30,
    session_id: uuid.UUID | None = None,
) -> ReviewMetrics:
    """
    Human correction rate, per-class accuracy against human review, and per-annotator throughput.
    Accuracy counts only a person's verdicts (confirmed, corrected, rejected), never auto-accepted events.
    """
    since = datetime.now(UTC) - timedelta(days=days)
    s, m = MovementEvent.status, MovementEvent.review_method
    human = m.in_(review.HUMAN_METHODS)
    verdict = s.in_(
        (MovementEventStatus.confirmed, MovementEventStatus.corrected, MovementEventStatus.rejected)
    )
    base = select(MovementEvent.class_id).where(
        MovementEvent.run_id.in_(annotation_service.latest_runs()),
        MovementEvent.source == AnnotationSource.auto,
    )
    if session_id:
        base = base.where(MovementEvent.session_id == session_id)
    stmt = base.add_columns(
        func.count().label("predictions"),
        func.count().filter(s.in_(review.PENDING)).label("pending"),
        func.count().filter(s == MovementEventStatus.confirmed, m == ReviewMethod.auto_rule).label("auto"),
        func.count().filter(verdict, human).label("reviewed"),
        func.count().filter(s == MovementEventStatus.confirmed, human).label("confirmed"),
        func.count().filter(s == MovementEventStatus.corrected, human).label("corrected"),
        func.count().filter(s == MovementEventStatus.rejected, human).label("rejected"),
    ).group_by(MovementEvent.class_id)
    classes = {c.id: c for c in db.scalars(select(MovementClass))}
    per_class, tot = (
        [],
        dict.fromkeys(
            ("predictions", "pending", "auto", "reviewed", "confirmed", "corrected", "rejected"), 0
        ),
    )
    for row in db.execute(stmt):
        c = classes[row.class_id]
        for k in tot:
            tot[k] += getattr(row, k)
        per_class.append(ClassMetric(movement_class=ClassRef(id=c.id, name=c.name, label=c.label),
                                     predictions=row.predictions, pending=row.pending, auto_accepted=row.auto,
                                     human_reviewed=row.reviewed, confirmed=row.confirmed, corrected=row.corrected,
                                     rejected=row.rejected, accuracy=_rate(row.confirmed, row.reviewed)))  # fmt: skip
    per_class.sort(key=lambda c: (-c.predictions, c.movement_class.label))

    r = MovementEventReview
    # A person's status changes (undoing a batch is not a review, so undo rows only take a batch's back).
    log = select(r).where(r.created_at >= since, r.actor_id.is_not(None))
    if session_id:
        log = log.where(
            r.event_id.in_(select(MovementEvent.id).where(MovementEvent.session_id == session_id))
        )
    log_sub = log.subquery()
    hour = func.date_trunc("hour", log_sub.c.created_at)
    ann_rows = db.execute(
        select(
            log_sub.c.actor_id,
            func.count().filter(log_sub.c.method != ReviewMethod.undo).label("reviews"),
            func.count().filter(log_sub.c.method == ReviewMethod.individual).label("individual"),
            func.count().filter(log_sub.c.method == ReviewMethod.bulk).label("bulk"),
            func.count().filter(log_sub.c.method == ReviewMethod.correction, log_sub.c.to_status == MovementEventStatus.corrected).label("corrections"),
            func.count().filter(log_sub.c.method == ReviewMethod.inspector).label("inspector"),
            func.count().filter(log_sub.c.to_status == MovementEventStatus.confirmed, log_sub.c.method != ReviewMethod.correction).label("confirmed"),
            func.count().filter(log_sub.c.to_status == MovementEventStatus.rejected).label("rejected"),
            func.count().filter(log_sub.c.to_status == MovementEventStatus.needs_review).label("flagged"),
            func.count(func.distinct(case((log_sub.c.method.in_((ReviewMethod.individual, ReviewMethod.correction, ReviewMethod.inspector)), hour)))).label("hours"),
            func.min(log_sub.c.created_at).label("first"),
            func.max(log_sub.c.created_at).label("last"),
        ).group_by(log_sub.c.actor_id)
    ).all()  # fmt: skip
    users = (
        {u.id: u for u in db.scalars(select(User).where(User.id.in_({a.actor_id for a in ann_rows})))}
        if ann_rows
        else {}
    )
    annotators = []
    for a in ann_rows:
        u = users.get(a.actor_id)
        if u is None:
            continue
        own = a.individual + a.corrections + a.inspector
        annotators.append(AnnotatorMetric(user=user_ref(u), reviews=a.reviews, individual=a.individual, bulk=a.bulk,  # type: ignore[arg-type]
                                          corrections=a.corrections, inspector=a.inspector, confirmed=a.confirmed,
                                          rejected=a.rejected, flagged=a.flagged, active_hours=a.hours,
                                          per_hour=round(own / a.hours, 2) if a.hours else None,
                                          first_at=a.first, last_at=a.last))  # fmt: skip
    annotators.sort(key=lambda a: (-a.reviews, a.user.name))

    day = func.date_trunc("day", r.created_at)
    daily_q = select(
        day.label("day"),
        func.count().filter(r.method.in_(review.HUMAN_METHODS)).label("human"),
        func.count().filter(r.method == ReviewMethod.auto_rule).label("auto"),
    ).where(r.created_at >= since)
    if session_id:
        daily_q = daily_q.where(
            r.event_id.in_(select(MovementEvent.id).where(MovementEvent.session_id == session_id))
        )
    daily = [DailyReviews(day=d.day.date(), human=d.human, auto_rule=d.auto)
             for d in db.execute(daily_q.group_by(day).order_by(day))]  # fmt: skip
    return ReviewMetrics(days=days, since=since, predictions=tot["predictions"], pending=tot["pending"],
                         auto_accepted=tot["auto"], human_reviewed=tot["reviewed"], confirmed=tot["confirmed"],
                         corrected=tot["corrected"], rejected=tot["rejected"],
                         correction_rate=_rate(tot["corrected"], tot["reviewed"]),
                         rejection_rate=_rate(tot["rejected"], tot["reviewed"]), per_class=per_class,
                         annotators=annotators, daily=daily)  # fmt: skip


# --- auto annotation -------------------------------------------------------------------------------


@router.get("/model-versions", response_model=list[ModelVersionRead])
def model_versions(db: DbSession, _: CurrentUser, kind: CvRunKind | None = None) -> list[ModelVersionRead]:
    """Registered model versions (every adapter + config that has run), most recently used first."""
    stmt = (
        select(ModelVersion, func.count(CvRun.id), func.max(CvRun.created_at))
        .outerjoin(CvRun, CvRun.model_version_id == ModelVersion.id)
        .group_by(ModelVersion.id)
    )
    if kind:
        stmt = stmt.where(ModelVersion.kind == kind.value)
    out = []
    for mv, n, last in db.execute(stmt):
        name, config = registry.configured(mv.kind) if mv.kind in registry.KINDS else ("", {})
        configured = (
            registry.target(name, mv.kind) == mv.adapter
            and mv.version.endswith(f"cfg:{registry.config_hash(name, config, mv.kind)}")
            if name
            else False
        )
        out.append(ModelVersionRead(id=mv.id, name=mv.name, version=mv.version, kind=mv.kind, adapter=mv.adapter,
                                    config=mv.config, created_at=mv.created_at, runs=n, last_run_at=last,
                                    configured=configured))  # fmt: skip
    out.sort(key=lambda v: (v.kind, -(v.last_run_at or v.created_at).timestamp()))
    return out


@router.post("/auto-annotate", response_model=AutoAnnotateResult, status_code=201)
def auto_annotate(body: AutoAnnotateRequest, db: DbSession, user: Processor) -> AutoAnnotateResult:
    """
    Run auto annotation on the ready videos of the chosen sessions (and videos), with a chosen model version
    per kind. Unchosen kinds use the configured adapter. Videos that aren't ready, or have nothing to
    classify, are skipped and listed.
    """
    kinds = [k.value for k in body.kinds] if body.kinds else list(get_settings().cv_default_kinds)
    setups: dict[str, tuple[str, dict]] = {}
    for kind, choice in body.models.items():
        if choice.model_version_id is not None:
            mv = db.get(ModelVersion, choice.model_version_id)
            if mv is None or mv.kind != kind.value:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    f"No {kind.value} model version {choice.model_version_id}",
                )
            setups[kind.value] = (registry.name_for(mv.adapter, kind.value), dict(mv.config))
        else:
            assert choice.adapter is not None
            try:
                cls = registry.resolve(choice.adapter, kind.value)
            except AdapterError as exc:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
            if registry.is_stub(cls):
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    f"{choice.adapter} is a documented stub, not a runnable model",
                )
            setups[kind.value] = (choice.adapter, dict(choice.config))  # fmt: skip
    stmt = select(Video)
    conds = []
    if body.session_ids:
        conds.append(Video.session_id.in_(body.session_ids))
    if body.video_ids:
        conds.append(Video.id.in_(body.video_ids))
    videos = db.scalars(
        stmt.where(or_(*conds)).order_by(Video.created_at, Video.id).limit(MAX_AUTO_VIDEOS + 1)
    ).all()
    if len(videos) > MAX_AUTO_VIDEOS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"More than {MAX_AUTO_VIDEOS} videos; choose fewer sessions",
        )
    found = (
        {s for (s,) in db.execute(select(CaptureSession.id).where(CaptureSession.id.in_(body.session_ids)))}
        if body.session_ids
        else set()
    )
    missing = [str(s) for s in body.session_ids if s not in found]
    if missing:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Sessions not found: {', '.join(missing)}")  # fmt: skip
    created, skipped = [], []
    for v in videos:
        ref = Ref(id=v.id, name=v.original_filename)
        if v.status != VideoStatus.ready:
            skipped.append(SkippedVideo(video=ref, reason=f"video is {v.status.value}"))
            continue
        if v.processing_hold in (ProcessingHold.held, ProcessingHold.rejected):
            skipped.append(SkippedVideo(video=ref, reason="waiting for the admin's approval"))
            continue
        try:
            made = runs_service.create_runs(db, v, kinds, body.stride, user.id, setups)
        except runs_service.RunRequestError as exc:
            skipped.append(SkippedVideo(video=ref, reason=str(exc)))
            continue
        created += [run_summary(r, v.original_filename, None) for r in made]
    return AutoAnnotateResult(videos=len(videos) - len(skipped), runs=created, skipped=skipped,
                              setups={k: {"adapter": n, "config": c} for k, (n, c) in setups.items()})  # fmt: skip
