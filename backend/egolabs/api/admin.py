"""The owner's controls: what waits for them (Requests) and their limits (Settings → Limits)."""

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from egolabs import app_settings
from egolabs.api.deps import AdminUser, CurrentUser, DbSession
from egolabs.events import record_event
from egolabs.models import ProcessingHold, Upload, UploadStatus, User, Video
from egolabs.pipelines import auto
from egolabs.schemas.admin import HeldVideo, LimitsUpdate, Requests, WaitingUpload
from egolabs.schemas.ingest import UploadReview

router = APIRouter(tags=["admin"])


@router.get("/settings/limits", response_model=app_settings.Limits)
def get_limits(db: DbSession, _: CurrentUser) -> app_settings.Limits:
    """The admin's limits (everyone can read them, so the upload page can say what waits for approval)."""
    return app_settings.get(db)


@router.patch("/settings/limits", response_model=app_settings.Limits)
def update_limits(body: LimitsUpdate, db: DbSession, admin: AdminUser) -> app_settings.Limits:
    values = body.model_dump(exclude_unset=True)
    limits = app_settings.put(db, values, admin.id)
    if values:
        record_event(db, "settings.limits_changed", "Limits changed", entity_type="settings", actor_id=admin.id,
                     data=limits.model_dump())  # fmt: skip
    db.commit()
    return limits


@router.get("/requests", response_model=Requests)
def list_requests(db: DbSession, _: AdminUser) -> Requests:
    """Uploads over the size limit and videos over the length limit, waiting for the admin, oldest first."""
    uploads = db.execute(
        select(Upload, User).outerjoin(User, User.id == Upload.created_by)
        .where(Upload.status == UploadStatus.awaiting_approval).order_by(Upload.created_at, Upload.id)
    ).all()  # fmt: skip
    videos = db.execute(
        select(Video, User).outerjoin(Upload, Upload.id == Video.upload_id).outerjoin(User, User.id == Upload.created_by)
        .where(Video.processing_hold == ProcessingHold.held).order_by(Video.created_at, Video.id)
    ).all()  # fmt: skip
    return Requests(
        uploads=[
            WaitingUpload(
                id=u.id,
                filename=u.filename,
                size_bytes=u.size_bytes,
                reason=u.approval_reason,
                created_at=u.created_at,
                uploaded_by_email=p.email if p else None,
                uploaded_by_name=p.name if p else None,
            )
            for u, p in uploads
        ],  # fmt: skip
        videos=[
            HeldVideo(
                id=v.id,
                filename=v.original_filename,
                duration_s=v.duration_s,
                reason=v.hold_reason,
                created_at=v.created_at,
                uploaded_by_email=p.email if p else None,
                uploaded_by_name=p.name if p else None,
            )
            for v, p in videos
        ],  # fmt: skip
    )


def _held(db: DbSession, video_id: uuid.UUID) -> Video:
    video = db.get(Video, video_id, with_for_update=True)
    if video is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Video not found")
    if video.processing_hold != ProcessingHold.held:
        raise HTTPException(status.HTTP_409_CONFLICT, "This video isn't waiting for approval")
    return video


@router.post("/requests/videos/{video_id}/allow", response_model=HeldVideo)
def allow_video(video_id: uuid.UUID, db: DbSession, admin: AdminUser) -> HeldVideo:
    """Let a long video be processed: the pipelines that run on new uploads start on it now."""
    video = _held(db, video_id)
    video.processing_hold = ProcessingHold.allowed
    record_event(db, "video.allowed", f"Allowed to process: {video.original_filename}", entity_type="video",
                 entity_id=video.id, actor_id=admin.id)  # fmt: skip
    db.commit()
    auto.start_for_video(db, video.id)
    return HeldVideo(id=video.id, filename=video.original_filename, duration_s=video.duration_s,
                     reason=video.hold_reason, created_at=video.created_at)  # fmt: skip


@router.post("/requests/videos/{video_id}/reject", response_model=HeldVideo)
def reject_video(video_id: uuid.UUID, body: UploadReview, db: DbSession, admin: AdminUser) -> HeldVideo:
    """Keep a long video from being processed (it stays in the library, unprocessed)."""
    video = _held(db, video_id)
    video.processing_hold = ProcessingHold.rejected
    if body.reason and body.reason.strip():
        video.hold_reason = f"{video.hold_reason}. Rejected: {body.reason.strip()}"
    record_event(db, "video.rejected", f"Not to be processed: {video.original_filename}", entity_type="video",
                 entity_id=video.id, actor_id=admin.id)  # fmt: skip
    db.commit()
    return HeldVideo(id=video.id, filename=video.original_filename, duration_s=video.duration_s,
                     reason=video.hold_reason, created_at=video.created_at)  # fmt: skip
