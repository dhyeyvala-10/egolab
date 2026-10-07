"""
Review and active learning (spec Phase 5).

- **Status changes** (`set_status`): confirm, reject, flag, or reopen an event. Its timeline segment follows
  (rejecting soft-deletes it, flagging sets its review flag), and the change is a row in the review log
  saying who made it and how (`individual`, `bulk`, `auto_rule`, `undo`).
- **Corrections** (`correct`) never edit a prediction: they go through the annotation service, which
  creates the corrected segment and a new event version whose parent is the prediction.
- **Auto-accept rules** confirm new predictions at or above a confidence, per class or by default, with no
  person involved (method `auto_rule`, so datasets can tell them from human review).
- **Bulk review** confirms or rejects every pending event matching a filter, as one batch that can be
  undone: undo puts back each event the batch changed that nobody has reviewed since.
- **Disagreement**: when a video has been classified by more than one model version, each new event is
  compared with the other versions' latest runs: 1 − the mean best temporal IoU with a same-class,
  same-hand event of each.
- **Queue priority**: `w_c·(1 − confidence) + w_d·disagreement + w_r·rarity`. Rarity places a class's count
  of current predictions `n` between the most and least common on a log scale:
  `(ln(1 + n_max) − ln(1 + n)) / (ln(1 + n_max) − ln(1 + n_min))`: 1 for the rarest, 0 for the most common.
"""

import uuid
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import ColumnElement, Select, and_, case, func, literal, or_, select
from sqlalchemy.orm import Session

from egolabs import annotations as annotation_service
from egolabs.config import get_settings
from egolabs.models import (
    Annotation,
    AnnotationSource,
    CvRun,
    CvRunKind,
    CvRunStatus,
    MovementClass,
    MovementEvent,
    MovementEventReview,
    MovementEventStatus,
    ReviewBatch,
    ReviewMethod,
    ReviewRule,
    User,
)
from egolabs.schemas.annotation import AnnotationUpdate

PENDING = (MovementEventStatus.auto_detected, MovementEventStatus.needs_review)
HUMAN_METHODS = (ReviewMethod.individual, ReviewMethod.bulk, ReviewMethod.correction, ReviewMethod.inspector)


class ReviewError(ValueError):
    """A review that can't be applied as asked (the API answers 409)."""


# --- which events --------------------------------------------------------------------------------------


def current() -> ColumnElement[bool]:
    """Events shown now: from each video's latest classification run, and not replaced by a correction."""
    return MovementEvent.run_id.in_(annotation_service.latest_runs()) & MovementEvent.superseded_at.is_(None)


@dataclass
class Filters:
    """What a queue, a summary, or a bulk action covers. Empty fields don't filter."""

    video_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    classes: list[str] = field(default_factory=list)
    object_label: str | None = None
    no_object: bool = False
    handedness: str | None = None
    statuses: list[MovementEventStatus] = field(default_factory=lambda: list(PENDING))
    min_confidence: float | None = None
    max_confidence: float | None = None
    event_ids: list[uuid.UUID] = field(default_factory=list)

    def dump(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in self.__dict__.items():
            if v in (None, [], False):
                continue
            out[k] = [str(x) for x in v] if isinstance(v, list) else str(v) if isinstance(v, uuid.UUID) else v
        return out


def apply_filters(stmt: Select, f: Filters) -> Select:
    stmt = stmt.where(current())
    if f.video_id:
        stmt = stmt.where(MovementEvent.video_id == f.video_id)
    if f.session_id:
        stmt = stmt.where(MovementEvent.session_id == f.session_id)
    if f.classes:
        stmt = stmt.where(
            MovementEvent.class_id.in_(select(MovementClass.id).where(MovementClass.name.in_(f.classes)))
        )
    if f.no_object:
        stmt = stmt.where(MovementEvent.object_label.is_(None))
    elif f.object_label:
        stmt = stmt.where(MovementEvent.object_label == f.object_label)
    if f.handedness:
        stmt = stmt.where(MovementEvent.handedness == f.handedness)
    if f.statuses:
        stmt = stmt.where(MovementEvent.status.in_(f.statuses))
    if f.min_confidence is not None:
        stmt = stmt.where(MovementEvent.confidence >= f.min_confidence)
    if f.max_confidence is not None:
        stmt = stmt.where(MovementEvent.confidence <= f.max_confidence)
    if f.event_ids:
        stmt = stmt.where(MovementEvent.id.in_(f.event_ids))
    return stmt


# --- priority ------------------------------------------------------------------------------------------


def class_counts():
    """SQL: current predictions per class (the rarity input)."""
    return (
        select(MovementEvent.class_id.label("class_id"), func.count().label("n"))
        .where(current(), MovementEvent.source == AnnotationSource.auto)
        .group_by(MovementEvent.class_id)
        .subquery("class_counts")
    )


def weights() -> dict[str, float]:
    w = get_settings().review_priority_weights
    return {k: float(w.get(k, 0.0)) for k in ("confidence", "disagreement", "rarity")}


def scored(stmt: Select) -> tuple[Select, ColumnElement[float], ColumnElement[float]]:
    """Add `rarity` and `priority` columns to an events query. Returns (query, rarity, priority)."""
    counts = class_counts()
    hi = func.ln(1.0 + select(func.max(counts.c.n)).scalar_subquery())
    lo = func.ln(1.0 + select(func.min(counts.c.n)).scalar_subquery())
    n = func.ln(1.0 + func.coalesce(counts.c.n, 0))
    rarity = case(
        (hi - lo <= 0, literal(0.0)), else_=func.greatest(0.0, func.least(1.0, (hi - n) / (hi - lo)))
    )
    w = weights()
    priority = (
        w["confidence"] * (1.0 - func.coalesce(MovementEvent.confidence, 1.0))
        + w["disagreement"] * func.coalesce(MovementEvent.disagreement, 0.0)
        + w["rarity"] * rarity
    )
    stmt = stmt.outerjoin(counts, counts.c.class_id == MovementEvent.class_id)
    return stmt.add_columns(rarity.label("rarity"), priority.label("priority")), rarity, priority


# --- status changes ------------------------------------------------------------------------------------


def set_status(
    db: Session,
    event: MovementEvent,
    target: MovementEventStatus,
    user: User,
    method: ReviewMethod = ReviewMethod.individual,
    *,
    batch_id: uuid.UUID | None = None,
) -> None:
    """Confirm, reject, flag (`needs_review`), or reopen (`auto_detected`) an event, with its segment."""
    if event.superseded_at is not None or event.status == MovementEventStatus.corrected:
        raise ReviewError("This event was corrected; review the correction instead")
    if target == MovementEventStatus.corrected:
        raise ReviewError("Correct an event by sending the corrected fields")
    if target == MovementEventStatus.auto_detected and event.source != AnnotationSource.auto:
        raise ReviewError("A correction is a person's work; it can be confirmed, flagged, or rejected")
    if event.status == target:
        return
    ann = db.get(Annotation, event.annotation_id)
    assert ann is not None
    annotation_service.log_review(db, event, target, method, user.id, batch_id=batch_id)
    # The segment follows; the event already has its new status, so the annotation service's sync is a no-op.
    if target == MovementEventStatus.rejected:
        annotation_service.delete(db, ann.id, user)
        return
    if ann.deleted_at is not None:
        annotation_service.restore(db, ann.id, user)
    flag = target == MovementEventStatus.needs_review
    if ann.needs_review != flag:
        annotation_service.update(db, ann.id, AnnotationUpdate(needs_review=flag), user)


@dataclass
class Correction:
    class_name: str | None = None
    start_frame: int | None = None
    end_frame: int | None = None
    handedness: str | None = None
    fingers: list[str] | None = None
    object_label: str | None = None
    clear_object: bool = False


def correct(db: Session, event: MovementEvent, body: Correction, user: User) -> MovementEvent:
    """
    Correct an event. A prediction is never edited: this creates a new event version (and corrected
    segment) whose parent is the prediction. Correcting a correction edits it (its segment keeps every
    revision). Returns the event that now holds the correction.
    """
    if event.superseded_at is not None:
        raise ReviewError("This event was already corrected; correct the newer version")
    ann = db.get(Annotation, event.annotation_id)
    assert ann is not None
    if ann.deleted_at is not None:  # rejected: bring it back to correct it
        annotation_service.restore(db, ann.id, user)
    cls = db.get(MovementClass, event.class_id)
    if body.class_name:
        cls = db.scalar(select(MovementClass).where(MovementClass.name == body.class_name))
        if cls is None:
            raise ReviewError(f"No movement class named {body.class_name!r}")
    assert cls is not None
    data = dict(ann.data or {})
    data["class"] = cls.name
    for key in ("handedness", "fingers"):
        value = getattr(body, key)
        if value is not None:
            data[key] = value
    if body.clear_object:
        data["object_label"], data["object_track_id"] = None, None
    elif body.object_label is not None and body.object_label != event.object_label:
        data["object_label"], data["object_track_id"] = body.object_label, None
    label = cls.label + (f" · {data['object_label']}" if data.get("object_label") else "")
    update = AnnotationUpdate(
        label=label[:200],
        frame_start=body.start_frame if body.start_frame is not None else ann.frame_start,
        frame_end=body.end_frame if body.end_frame is not None else ann.frame_end,
        needs_review=False,
    )
    before = {k: getattr(ann, k) for k in ("label", "frame_start", "frame_end", "data")}
    after = {
        "label": update.label,
        "frame_start": update.frame_start,
        "frame_end": update.frame_end,
        "data": data,
    }
    if before == after and ann.source == AnnotationSource.auto:
        raise ReviewError("Nothing to correct: that is what the model predicted. Confirm it instead")
    held = annotation_service.update(db, ann.id, update, user, meta=data)
    version = db.scalar(select(MovementEvent).where(MovementEvent.annotation_id == held.id))
    assert version is not None
    if version.id == event.id and version.status != MovementEventStatus.confirmed:  # a correction, re-edited
        annotation_service.log_review(
            db, version, MovementEventStatus.confirmed, ReviewMethod.correction, user.id
        )
    return version


# --- auto-accept rules ---------------------------------------------------------------------------------


def _rules(db: Session) -> tuple[dict[uuid.UUID | None, ReviewRule], ReviewRule | None]:
    rules = {r.class_id: r for r in db.scalars(select(ReviewRule))}
    return rules, rules.get(None)


def rule_for(
    rules: dict[uuid.UUID | None, ReviewRule], default: ReviewRule | None, class_id: uuid.UUID
) -> ReviewRule | None:
    """A class's own rule (even switched off: the class opted out), else the default. None if off."""
    rule = rules.get(class_id, default)
    return rule if rule is not None and rule.enabled else None


def eligible(event: MovementEvent, rule: ReviewRule | None) -> bool:
    return (
        rule is not None
        and event.source == AnnotationSource.auto
        and event.status == MovementEventStatus.auto_detected  # never a flagged event
        and event.superseded_at is None
        and event.confidence is not None
        and event.confidence >= rule.min_confidence
    )


def auto_accept(db: Session, events: Iterable[MovementEvent], batch_id: uuid.UUID | None = None) -> int:
    """Confirm the events the rules accept (method `auto_rule`). Returns how many."""
    rules, default = _rules(db)
    if not any(r.enabled for r in rules.values()):
        return 0
    n = 0
    for e in events:
        rule = rule_for(rules, default, e.class_id)
        if eligible(e, rule):
            assert rule is not None
            annotation_service.log_review(db, e, MovementEventStatus.confirmed, ReviewMethod.auto_rule, None,
                                          batch_id=batch_id, rule_id=rule.id)  # fmt: skip
            n += 1
    return n


def rule_candidates(db: Session, f: Filters) -> Select:
    """Current pending predictions the rules would accept now (for 'apply to existing')."""
    rules, default = _rules(db)
    conds = []
    for class_id, rule in rules.items():
        if class_id is not None and rule.enabled:
            conds.append(
                and_(MovementEvent.class_id == class_id, MovementEvent.confidence >= rule.min_confidence)
            )
    if default is not None and default.enabled:
        own = [cid for cid in rules if cid is not None]
        conds.append(and_(MovementEvent.class_id.notin_(own) if own else literal(True),
                          MovementEvent.confidence >= default.min_confidence))  # fmt: skip
    stmt = select(MovementEvent).where(
        MovementEvent.source == AnnotationSource.auto,
        MovementEvent.status == MovementEventStatus.auto_detected,
    )
    stmt = apply_filters(stmt, Filters(**{**f.__dict__, "statuses": [MovementEventStatus.auto_detected]}))
    return stmt.where(or_(*conds)) if conds else stmt.where(literal(False))


# --- bulk review ---------------------------------------------------------------------------------------


def bulk_query(f: Filters) -> Select:
    statuses = [s for s in f.statuses if s in PENDING] or list(PENDING)
    return apply_filters(select(MovementEvent), Filters(**{**f.__dict__, "statuses": statuses}))


def bulk(
    db: Session,
    f: Filters,
    action: MovementEventStatus,
    user: User,
    *,
    method: ReviewMethod = ReviewMethod.bulk,
) -> ReviewBatch:
    """Confirm or reject every pending event matching `f`, as one undoable batch."""
    if action not in (MovementEventStatus.confirmed, MovementEventStatus.rejected):
        raise ReviewError("A bulk review confirms or rejects")
    stmt = bulk_query(f) if method == ReviewMethod.bulk else rule_candidates(db, f)
    count = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    limit = get_settings().review_bulk_max
    if count > limit:
        raise ReviewError(
            f"{count} events match; one bulk review changes at most {limit}. Narrow the filters"
        )
    batch = ReviewBatch(action=action, filters={**f.dump(), "method": method.value}, actor_id=user.id)
    db.add(batch)
    db.flush()
    events = db.scalars(stmt.order_by(MovementEvent.id).with_for_update(of=MovementEvent)).all()
    if method == ReviewMethod.auto_rule:
        batch.count = auto_accept(db, events, batch_id=batch.id)
    else:
        for e in events:
            set_status(db, e, action, user, ReviewMethod.bulk, batch_id=batch.id)
        batch.count = len(events)
    return batch


def undo(db: Session, batch: ReviewBatch, user: User) -> int:
    """Put back what a batch changed, for each event nobody has reviewed since. Returns how many."""
    if batch.undone_at is not None:
        raise ReviewError("This batch was already undone")
    rows = db.execute(
        select(MovementEventReview.event_id, MovementEventReview.from_status).where(
            MovementEventReview.batch_id == batch.id, MovementEventReview.to_status == batch.action
        )
    ).all()
    n = 0
    for event_id, from_status in rows:
        e = db.get(MovementEvent, event_id, with_for_update=True)
        if e is None or e.review_batch_id != batch.id or e.status != batch.action or from_status is None:
            continue  # reviewed again since (or gone): leave it
        set_status(db, e, MovementEventStatus(from_status), user, ReviewMethod.undo)
        n += 1
    batch.undone_at, batch.undone_by, batch.undone_count = datetime.now(UTC), user.id, n
    return n


# --- model disagreement --------------------------------------------------------------------------------


def _tiou(a: tuple[int, int], b: tuple[int, int]) -> float:
    inter = min(a[1], b[1]) - max(a[0], b[0]) + 1
    if inter <= 0:
        return 0.0
    return inter / (max(a[1], b[1]) - min(a[0], b[0]) + 1)


def compare_versions(db: Session, run: CvRun) -> int:
    """
    Set disagreement on `run`'s events against each other model version's latest successful classification
    of the same video. Returns how many other versions it compared with (0: disagreement stays unknown).
    """
    others = db.scalars(
        select(CvRun)
        .distinct(CvRun.model_version_id)
        .where(
            CvRun.video_id == run.video_id,
            CvRun.kind == CvRunKind.movement.value,
            CvRun.status == CvRunStatus.succeeded,
            CvRun.id != run.id,
            CvRun.model_version_id != run.model_version_id,
        )  # fmt: skip
        .order_by(CvRun.model_version_id, CvRun.finished_at.desc(), CvRun.id)
    ).all()
    events = db.scalars(
        select(MovementEvent).where(
            MovementEvent.run_id == run.id, MovementEvent.source == AnnotationSource.auto
        )
    ).all()
    if not others:
        for e in events:
            e.disagreement, e.compared_versions = None, 0
        return 0
    theirs: dict[uuid.UUID, dict[tuple[uuid.UUID, str], list[tuple[int, int]]]] = {
        o.id: defaultdict(list) for o in others
    }
    rows = db.execute(
        select(
            MovementEvent.run_id,
            MovementEvent.class_id,
            MovementEvent.handedness,
            MovementEvent.start_frame,
            MovementEvent.end_frame,
        ).where(  # fmt: skip
            MovementEvent.run_id.in_([o.id for o in others]), MovementEvent.source == AnnotationSource.auto
        )
    ).all()
    for run_id, class_id, hand, start, end in rows:
        theirs[run_id][(class_id, hand)].append((start, end))
    for e in events:
        span = (e.start_frame, e.end_frame)
        best = [max((_tiou(span, s) for s in theirs[o.id].get((e.class_id, e.handedness), [])), default=0.0)
                for o in others]  # fmt: skip
        e.disagreement = round(1.0 - sum(best) / len(best), 4)
        e.compared_versions = len(others)
    return len(others)


def after_classification(db: Session, run: CvRun) -> dict[str, int]:
    """A classification run's events are stored: compare model versions, then apply auto-accept rules."""
    db.flush()
    compared = compare_versions(db, run)
    events = db.scalars(select(MovementEvent).where(MovementEvent.run_id == run.id)).all()
    return {"compared_versions": compared, "auto_accepted": auto_accept(db, events)}
