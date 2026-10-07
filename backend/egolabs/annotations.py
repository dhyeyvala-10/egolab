"""
Annotation changes, each recorded as an append-only revision.

- Human (and corrected) annotations are edited in place; every change adds a revision holding the
  full state after it, so any earlier state can be read back.
- Content changes to an AI annotation never touch it: they create a new `auto_corrected` annotation
  whose parent is the prediction, and the prediction is marked superseded (principles 4 and 5).
  Flagging for review is not a content change, so it applies to AI annotations directly.
- Deletes are soft: the row stays, marked deleted, with the delete in its history.
- A movement event (Phase 4) follows its timeline segment: flagging it marks it for review, deleting it
  rejects it, and correcting it creates a new event version (Phase 5): an `auto_corrected` event on the
  correction, whose parent is the predicted event, which is marked corrected. Every such change is a row in
  the event's review log (method `inspector`, or `correction`).
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from egolabs.models import (
    Annotation,
    AnnotationRevision,
    AnnotationSource,
    CvRun,
    CvRunStatus,
    MovementClass,
    MovementEvent,
    MovementEventReview,
    MovementEventStatus,
    ReviewMethod,
    RevisionAction,
    User,
    Video,
)
from egolabs.schemas.annotation import AnnotationCreate, AnnotationUpdate, validate_data

CONTENT_FIELDS = ("label", "category", "frame_start", "frame_end", "data")


def _json(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value"):  # enums
        return value.value
    return value


def snapshot(a: Annotation) -> dict[str, Any]:
    fields = (
        "type", "label", "category", "frame_start", "frame_end", "data", "source", "confidence",
        "model_version_id", "parent_annotation_id", "needs_review", "deleted_at", "superseded_at",
    )  # fmt: skip
    return {f: _json(getattr(a, f)) for f in fields}


def _revise(
    db: Session,
    a: Annotation,
    action: RevisionAction,
    actor: User,
    changes: dict[str, Any] | None = None,
    related: uuid.UUID | None = None,
) -> None:
    now = datetime.now(UTC)
    if action != RevisionAction.created:
        a.revision += 1
        a.updated_at, a.updated_by = now, actor.id
    db.add(
        AnnotationRevision(
            annotation_id=a.id,
            revision=a.revision,
            action=action,
            changes=changes or {},
            snapshot=snapshot(a),
            actor_id=actor.id,
            related_annotation_id=related,
        )
    )


def log_review(
    db: Session,
    event: MovementEvent,
    status: MovementEventStatus,
    method: ReviewMethod,
    actor_id: uuid.UUID | None,
    *,
    batch_id: uuid.UUID | None = None,
    rule_id: uuid.UUID | None = None,
    related_event_id: uuid.UUID | None = None,
) -> None:
    """Set an event's status and append the change to its review log."""
    db.add(MovementEventReview(event_id=event.id, from_status=event.status, to_status=status, method=method,
                               actor_id=actor_id, batch_id=batch_id, rule_id=rule_id,
                               related_event_id=related_event_id, class_id=event.class_id))  # fmt: skip
    event.status, event.reviewed_by, event.reviewed_at = status, actor_id, datetime.now(UTC)
    event.review_method, event.review_batch_id, event.review_rule_id = method, batch_id, rule_id


def _event_of(db: Session, a: Annotation) -> MovementEvent | None:
    return db.scalar(select(MovementEvent).where(MovementEvent.annotation_id == a.id))


def _sync_event(
    db: Session,
    a: Annotation,
    user: User,
    status: MovementEventStatus,
    only_from: tuple[MovementEventStatus, ...] = (),
) -> None:
    """Move the movement event behind annotation `a` (if any) to `status` (only from `only_from`, if given)."""
    event = _event_of(db, a)
    if event is None or event.status == status or (only_from and event.status not in only_from):
        return
    log_review(db, event, status, ReviewMethod.inspector, user.id)


EVENT_DATA_KEYS = ("handedness", "fingers", "object_label", "object_track_id")


def class_for_segment(
    label: str, data: dict[str, Any] | None, classes: list[MovementClass]
) -> MovementClass | None:
    """
    The movement class a (corrected) segment states. The label wins: relabelling a segment in the inspector
    changes its label, not the copied `data`; then `data["class"]`.
    """
    head = label.split(" · ")[0].strip().lower()
    cls = next((c for c in classes if head in (c.label.lower(), c.name, c.name.replace("_", " "))), None)
    if cls is None and (data or {}).get("class"):
        cls = next((c for c in classes if c.name == data["class"]), None)  # type: ignore[index]
    return cls


def _event_fields(db: Session, a: Annotation, fallback_class: uuid.UUID) -> dict[str, Any]:
    """An event's fields as its (corrected) segment states them: frames, class, hand, fingers, object."""
    data = a.data or {}
    cls = class_for_segment(a.label, data, list(db.scalars(select(MovementClass))))
    out: dict[str, Any] = {"class_id": cls.id if cls else fallback_class, "start_frame": a.frame_start,
                           "end_frame": a.frame_end}  # fmt: skip
    for key in EVENT_DATA_KEYS:
        if key in data:
            out[key] = data[key]
    return out


def _seconds(event: MovementEvent, video: Video | None, frame: int) -> float:
    if frame == event.start_frame:
        return event.start_s
    if frame == event.end_frame:
        return event.end_s
    fps = (video.fps if video else None) or 30.0
    return frame / fps


def _correct_event(db: Session, prediction: Annotation, correction: Annotation, user: User) -> None:
    """A correction of a predicted event's segment: a new event version on the correction (Phase 5)."""
    event = _event_of(db, prediction)
    if event is None:
        return
    video = db.get(Video, event.video_id)
    fields = _event_fields(db, correction, event.class_id)
    version = MovementEvent(
        id=uuid.uuid4(), annotation_id=correction.id, video_id=event.video_id, session_id=event.session_id,
        run_id=event.run_id, hand_run_id=event.hand_run_id, object_run_id=event.object_run_id,
        model_version_id=event.model_version_id, class_id=fields["class_id"],
        start_frame=fields["start_frame"], end_frame=fields["end_frame"],
        start_s=_seconds(event, video, fields["start_frame"]), end_s=_seconds(event, video, fields["end_frame"]),
        handedness=fields.get("handedness", event.handedness), hand_track_id=event.hand_track_id,
        fingers=list(fields.get("fingers", event.fingers)),
        object_track_id=fields.get("object_track_id", event.object_track_id),
        object_label=fields.get("object_label", event.object_label),
        confidence=None, source=AnnotationSource.auto_corrected, parent_event_id=event.id,
        status=MovementEventStatus.confirmed, reviewed_by=user.id, reviewed_at=datetime.now(UTC),
        review_method=ReviewMethod.correction,
        # What the model saw: the prediction's evidence frames, marked as inherited.
        evidence={**(event.evidence or {}), "inherited_from": str(event.id)}, attributes=dict(event.attributes or {}),
    )  # fmt: skip
    db.add(version)
    db.flush()
    db.add(MovementEventReview(event_id=version.id, from_status=None, to_status=MovementEventStatus.confirmed,
                               method=ReviewMethod.correction, actor_id=user.id, related_event_id=event.id,
                               class_id=version.class_id))  # fmt: skip
    event.superseded_at = datetime.now(UTC)
    log_review(
        db,
        event,
        MovementEventStatus.corrected,
        ReviewMethod.correction,
        user.id,
        related_event_id=version.id,
    )


def _follow_event(db: Session, a: Annotation) -> None:
    """An edit to a correction's segment (human-owned, edited in place): its event version follows."""
    event = _event_of(db, a)
    if event is None or event.source == AnnotationSource.auto:
        return
    video = db.get(Video, event.video_id)
    fields = _event_fields(db, a, event.class_id)
    start_s, end_s = (
        _seconds(event, video, fields["start_frame"]),
        _seconds(event, video, fields["end_frame"]),
    )
    for key, value in fields.items():
        setattr(event, key, list(value) if key == "fingers" else value)
    event.start_s, event.end_s = start_s, end_s


def _check_frames(video: Video, start: int, end: int) -> None:
    if end < start:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "frame_end must be at or after frame_start"
        )
    if video.frame_count is not None and end >= video.frame_count:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Frame {end} is past the end of the video (frames 0–{video.frame_count - 1})",
        )


def create(db: Session, video: Video, body: AnnotationCreate, user: User) -> Annotation:
    _check_frames(video, body.frame_start, body.frame_end)
    a = Annotation(
        id=uuid.uuid4(),
        video_id=video.id,
        type=body.type,
        label=body.label,
        category=body.category,
        frame_start=body.frame_start,
        frame_end=body.frame_end,
        data=body.data,
        source=AnnotationSource.human,
        needs_review=body.needs_review,
        created_by=user.id,
        revision=1,
    )
    db.add(a)
    db.flush()
    _revise(db, a, RevisionAction.created, user)
    return a


def _locked(db: Session, annotation_id: uuid.UUID) -> Annotation:
    a = db.get(Annotation, annotation_id, with_for_update=True)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Annotation not found")
    return a


def update(
    db: Session,
    annotation_id: uuid.UUID,
    body: AnnotationUpdate,
    user: User,
    *,
    meta: dict[str, Any] | None = None,
) -> Annotation:
    """
    Apply an edit. Returns the annotation that now holds it (a new correction for AI annotations).
    `meta` replaces `data` with server-written metadata (a movement event's class, hand, and object on its
    segment), which the user-facing data validation doesn't cover.
    """
    a = _locked(db, annotation_id)
    if body.revision is not None and body.revision != a.revision:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"This annotation changed since you loaded it (revision {a.revision}, you had {body.revision})",
        )
    if a.deleted_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Annotation is deleted; restore it before editing")
    if a.superseded_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Annotation was corrected; edit the correction instead")

    sent = body.model_dump(exclude_unset=True, exclude={"revision"})
    content = {k: v for k, v in sent.items() if k in CONTENT_FIELDS and v is not None}
    if "data" in content:
        try:
            content["data"] = validate_data(a.type, content["data"])
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    if meta is not None:
        content["data"] = meta
    content = {k: v for k, v in content.items() if getattr(a, k) != v}
    changes = {k: {"from": _json(getattr(a, k)), "to": _json(v)} for k, v in content.items()}
    if changes:
        video = db.get(Video, a.video_id)
        assert video is not None
        _check_frames(video, content.get("frame_start", a.frame_start), content.get("frame_end", a.frame_end))

    flag = sent.get("needs_review")
    flag_changed = flag is not None and flag != a.needs_review

    if changes and a.source == AnnotationSource.auto:
        correction = Annotation(
            id=uuid.uuid4(),
            video_id=a.video_id,
            type=a.type,
            label=content.get("label", a.label),
            category=content.get("category", a.category),
            frame_start=content.get("frame_start", a.frame_start),
            frame_end=content.get("frame_end", a.frame_end),
            data=content.get("data", a.data),
            source=AnnotationSource.auto_corrected,
            model_version_id=a.model_version_id,
            parent_annotation_id=a.id,
            needs_review=flag if flag is not None else a.needs_review,
            created_by=user.id,
            revision=1,
        )
        db.add(correction)
        db.flush()
        _revise(db, correction, RevisionAction.created, user, changes, related=a.id)
        a.superseded_at = datetime.now(UTC)
        _revise(db, a, RevisionAction.superseded, user, related=correction.id)
        _correct_event(db, a, correction, user)
        return correction

    if changes:
        for k, v in content.items():
            setattr(a, k, v)
        if flag_changed:
            a.needs_review = bool(flag)
            changes["needs_review"] = {"from": not flag, "to": flag}
        _revise(db, a, RevisionAction.updated, user, changes)
        _follow_event(db, a)
    elif flag_changed:
        a.needs_review = bool(flag)
        action = RevisionAction.flagged if flag else RevisionAction.unflagged
        _revise(db, a, action, user, {"needs_review": {"from": not flag, "to": flag}})
        if flag:
            _sync_event(db, a, user, MovementEventStatus.needs_review,
                        (MovementEventStatus.auto_detected, MovementEventStatus.confirmed))  # fmt: skip
        else:
            back = (
                MovementEventStatus.auto_detected
                if a.source == AnnotationSource.auto
                else MovementEventStatus.confirmed
            )
            _sync_event(db, a, user, back, (MovementEventStatus.needs_review,))
    return a


def delete(db: Session, annotation_id: uuid.UUID, user: User) -> Annotation:
    a = _locked(db, annotation_id)
    if a.deleted_at is None:
        a.deleted_at, a.deleted_by = datetime.now(UTC), user.id
        _revise(
            db, a, RevisionAction.deleted, user, {"deleted_at": {"from": None, "to": _json(a.deleted_at)}}
        )
        _sync_event(db, a, user, MovementEventStatus.rejected,
                    (MovementEventStatus.auto_detected, MovementEventStatus.needs_review, MovementEventStatus.confirmed))  # fmt: skip
    return a


def restore(db: Session, annotation_id: uuid.UUID, user: User) -> Annotation:
    a = _locked(db, annotation_id)
    if a.deleted_at is not None:
        changes = {"deleted_at": {"from": _json(a.deleted_at), "to": None}}
        a.deleted_at, a.deleted_by = None, None
        _revise(db, a, RevisionAction.restored, user, changes)
        if a.source == AnnotationSource.auto:
            back = MovementEventStatus.needs_review if a.needs_review else MovementEventStatus.auto_detected
        else:  # a correction is a person's work: restored, it stands confirmed
            back = MovementEventStatus.confirmed
        _sync_event(db, a, user, back, (MovementEventStatus.rejected,))
    return a


def latest_runs():
    """SQL: ids of each video's latest successful run of each kind."""
    return (
        select(CvRun.id)
        .distinct(CvRun.video_id, CvRun.kind)
        .where(CvRun.status == CvRunStatus.succeeded)
        .order_by(CvRun.video_id, CvRun.kind, CvRun.finished_at.desc(), CvRun.id)
    )


def from_current_runs():
    """
    SQL condition: not AI output of an older model run. Re-running a model on a video replaces the previous
    run's segments on the timeline (the old run's output stays in the database and its Parquet files).
    """
    return Annotation.cv_run_id.is_(None) | Annotation.cv_run_id.in_(latest_runs())


def active():
    """SQL condition for annotations that are shown: not deleted, not replaced by a correction or a newer run."""
    return (Annotation.deleted_at.is_(None)) & (Annotation.superseded_at.is_(None)) & from_current_runs()
