"""What waits for the owner: uploads over their size limit (before any of it is sent) and videos over their
length limit (before anything processes them). The owner allows or rejects each one (Settings → Requests).
The owner's own uploads never wait."""

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from egolabs import app_settings
from egolabs.events import record_event
from egolabs.format import human_bytes, human_duration
from egolabs.models import ProcessingHold, Role, Upload, User, Video


def upload_needs_approval(db: Session, user: User, size_bytes: int) -> str | None:
    """Why an upload of this size must wait for the owner, or None."""
    limit = app_settings.get(db).upload_max_bytes
    if user.role == Role.admin or limit is None or size_bytes <= limit:
        return None
    return f"{human_bytes(size_bytes)} is over the {human_bytes(limit)} upload limit"


def hold_if_too_long(db: Session, video: Video) -> bool:
    """Hold a just-ingested video longer than the owner's limit (unless the owner uploaded it). Returns whether
    it is held; the caller commits."""
    if video.processing_hold is not None:
        return video.processing_hold != ProcessingHold.allowed
    limit = app_settings.get(db).video_max_seconds
    if limit is None or video.duration_s is None or video.duration_s <= limit:
        return False
    upload = db.get(Upload, video.upload_id) if video.upload_id else None
    uploader = db.get(User, upload.created_by) if upload and upload.created_by else None
    if uploader is not None and uploader.role == Role.admin:
        return False
    video.processing_hold = ProcessingHold.held
    video.hold_reason = f"{human_duration(video.duration_s)} is over the {human_duration(limit)} length limit"
    record_event(db, "video.held", f"Waiting for the admin: {video.original_filename} ({video.hold_reason})",
                 entity_type="video", entity_id=video.id, actor_id=uploader.id if uploader else None)  # fmt: skip
    return True


def mark_reviewed(upload: Upload, by: uuid.UUID) -> None:
    upload.reviewed_by, upload.reviewed_at = by, datetime.now(UTC)
