"""Resumable uploads straight from the browser to object storage (S3 multipart with presigned part URLs).

People see only their own uploads; the admin sees everyone's, with who sent them. An upload over the admin's
size limit waits (`awaiting_approval`) before any of it is sent, until the admin allows or rejects it."""

import re
import uuid
from datetime import UTC, datetime
from typing import Annotated

from botocore.exceptions import ClientError
from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import func, select

from egolabs import approvals, storage
from egolabs.api.deps import AdminUser, CurrentUser, DbSession, Writer
from egolabs.config import get_settings
from egolabs.events import record_event
from egolabs.ingest.formats import SUPPORTED_UPLOAD_EXTENSIONS, upload_kind
from egolabs.jobs import enqueue_job
from egolabs.models import CaptureSession, Role, Upload, UploadStatus, User
from egolabs.schemas import Page
from egolabs.schemas.ingest import (
    PartUrl,
    PartUrlRequest,
    PartUrlResponse,
    UploadComplete,
    UploadCreate,
    UploadDetail,
    UploadedPart,
    UploadRead,
    UploadReview,
)

router = APIRouter(prefix="/uploads", tags=["uploads"])
PART_URL_TTL_S = 3600


def _safe_name(filename: str) -> str:
    base = filename.replace("\\", "/").rsplit("/", 1)[-1]
    return re.sub(r"[^A-Za-z0-9._-]+", "_", base)[:200] or "file"


def _get_own(db: DbSession, upload_id: uuid.UUID, user: User) -> Upload:
    """The upload, if it's this person's (or they're the admin). Anyone else's is "not found": people don't
    learn about each other's uploads."""
    upload = db.get(Upload, upload_id)
    if upload is None or (upload.created_by != user.id and user.role != Role.admin):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Upload not found")
    return upload


def _received(upload: Upload) -> tuple[list[UploadedPart], int | None, datetime | None]:
    """Parts already in storage while uploading: the parts, their bytes, and when the last arrived."""
    if upload.status != UploadStatus.uploading or not upload.s3_upload_id:
        return [], None, None
    try:
        parts = [UploadedPart(**p) for p in storage.list_parts(get_settings().s3_bucket_raw, upload.staging_key,
                                                                 upload.s3_upload_id)]  # fmt: skip
    except ClientError:
        return [], None, None
    last = max((p.last_modified for p in parts if p.last_modified), default=None)
    return parts, sum(p.size for p in parts), last


def _read(upload: Upload, people: dict[uuid.UUID, User], cls: type[UploadRead] = UploadRead) -> UploadRead:
    out = cls.model_validate(upload)
    who = people.get(upload.created_by) if upload.created_by else None
    if who is not None:
        out.uploaded_by_email, out.uploaded_by_name = who.email, who.name
    parts, out.received_bytes, out.last_data_at = _received(upload)
    if isinstance(out, UploadDetail):
        out.uploaded_parts = parts
    return out


def _people(db: DbSession, uploads: list[Upload]) -> dict[uuid.UUID, User]:
    ids = {u.created_by for u in uploads if u.created_by}
    return {u.id: u for u in db.scalars(select(User).where(User.id.in_(ids))).all()} if ids else {}


def _require_uploading(upload: Upload) -> None:
    if upload.status != UploadStatus.uploading or not upload.s3_upload_id:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Upload is {upload.status.value}, not uploading")


@router.post("", response_model=UploadRead, status_code=status.HTTP_201_CREATED)
def create_upload(body: UploadCreate, db: DbSession, user: Writer) -> Upload:
    settings = get_settings()
    kind = upload_kind(body.filename)
    if kind is None:
        supported = ", ".join(sorted(SUPPORTED_UPLOAD_EXTENSIONS))
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unsupported file type. Supported: {supported}"
        )
    if body.size_bytes > settings.max_upload_bytes:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "File is larger than the upload limit")
    if body.session_id and db.get(CaptureSession, body.session_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Session not found")

    upload_id = uuid.uuid4()
    key = f"staging/{upload_id}/{_safe_name(body.filename)}"
    upload = Upload(
        id=upload_id,
        filename=body.filename.replace("\\", "/").rsplit("/", 1)[-1][:1024],
        content_type=body.content_type,
        size_bytes=body.size_bytes,
        kind=kind,
        staging_key=key,
        part_size=storage.part_size_for(body.size_bytes),
        session_id=body.session_id,
        sequence_fps=body.sequence_fps,
        created_by=user.id,
    )
    reason = approvals.upload_needs_approval(db, user, body.size_bytes)
    if reason:
        # Nothing is sent until the admin allows it; then the uploader's page carries on by itself.
        upload.status, upload.approval_reason = UploadStatus.awaiting_approval, reason
        db.add(upload)
        record_event(db, "upload.approval_requested", f"Waiting for the admin: {upload.filename} ({reason})",
                     entity_type="upload", entity_id=upload_id, actor_id=user.id)  # fmt: skip
    else:
        upload.s3_upload_id = storage.create_multipart(settings.s3_bucket_raw, key, body.content_type)
        db.add(upload)
    db.commit()
    return upload


@router.get("", response_model=Page[UploadRead])
def list_uploads(
    db: DbSession,
    user: CurrentUser,
    session_id: uuid.UUID | None = None,
    status_: Annotated[UploadStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[UploadRead]:
    stmt = select(Upload)
    if user.role != Role.admin:
        stmt = stmt.where(Upload.created_by == user.id)
    if session_id:
        stmt = stmt.where(Upload.session_id == session_id)
    if status_:
        stmt = stmt.where(Upload.status == status_)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(
        db.scalars(stmt.order_by(Upload.created_at.desc(), Upload.id).limit(limit).offset(offset)).all()
    )
    people = _people(db, rows)
    return Page[UploadRead](items=[_read(r, people) for r in rows], total=total, limit=limit, offset=offset)


@router.get("/{upload_id}", response_model=UploadDetail)
def get_upload(upload_id: uuid.UUID, db: DbSession, user: CurrentUser) -> UploadDetail:
    upload = _get_own(db, upload_id, user)
    detail = _read(upload, _people(db, [upload]), UploadDetail)
    assert isinstance(detail, UploadDetail)
    return detail


@router.post("/{upload_id}/parts", response_model=PartUrlResponse)
def sign_parts(upload_id: uuid.UUID, body: PartUrlRequest, db: DbSession, user: Writer) -> PartUrlResponse:
    upload = _get_own(db, upload_id, user)
    _require_uploading(upload)
    count = max(1, -(-upload.size_bytes // upload.part_size))
    bad = [n for n in body.part_numbers if not 1 <= n <= count]
    if bad:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"Part numbers out of range 1–{count}: {bad}"
        )
    bucket = get_settings().s3_bucket_raw
    urls = [
        PartUrl(
            part_number=n,
            url=storage.presign_part(bucket, upload.staging_key, upload.s3_upload_id, n, PART_URL_TTL_S),
        )
        for n in sorted(set(body.part_numbers))
    ]
    return PartUrlResponse(urls=urls, expires_in=PART_URL_TTL_S)


@router.post("/{upload_id}/complete", response_model=UploadRead, status_code=status.HTTP_202_ACCEPTED)
def complete_upload(upload_id: uuid.UUID, body: UploadComplete, db: DbSession, user: Writer) -> Upload:
    upload = _get_own(db, upload_id, user)
    _require_uploading(upload)
    count = max(1, -(-upload.size_bytes // upload.part_size))
    numbers = sorted(p.part_number for p in body.parts)
    if numbers != list(range(1, count + 1)):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"Expected parts 1–{count}, each exactly once"
        )

    bucket = get_settings().s3_bucket_raw
    try:
        storage.complete_multipart(
            bucket, upload.staging_key, upload.s3_upload_id, [(p.part_number, p.etag) for p in body.parts]
        )
    except ClientError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Storage rejected the upload: {exc.response.get('Error', {}).get('Message', exc)}",
        ) from exc
    stored = storage.object_size(bucket, upload.staging_key)
    if stored != upload.size_bytes:
        upload.status = UploadStatus.failed
        upload.error = f"Stored {stored} bytes, expected {upload.size_bytes}"
        db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, upload.error)

    upload.status = UploadStatus.processing
    upload.completed_at = datetime.now(UTC)
    db.commit()
    job = enqueue_job(db, "ingest.upload", {"upload_id": str(upload.id)}, created_by=user.id)
    upload.job_id = job.id
    db.commit()
    return upload


@router.delete("/{upload_id}", status_code=status.HTTP_204_NO_CONTENT)
def abort_upload(upload_id: uuid.UUID, db: DbSession, user: Writer) -> Response:
    """Cancel an upload still in progress (or still waiting for the admin): the uploader's own, or anyone's
    for the admin. What was sent is thrown away."""
    upload = _get_own(db, upload_id, user)
    if upload.status == UploadStatus.awaiting_approval:
        upload.status = UploadStatus.aborted
    else:
        _require_uploading(upload)
        storage.abort_multipart(get_settings().s3_bucket_raw, upload.staging_key, upload.s3_upload_id)
        upload.status = UploadStatus.aborted
    if upload.created_by != user.id:
        record_event(db, "upload.cancelled", f"Upload cancelled by the admin: {upload.filename}", entity_type="upload",
                     entity_id=upload.id, actor_id=user.id)  # fmt: skip
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _awaiting(db: DbSession, upload_id: uuid.UUID) -> Upload:
    upload = db.get(Upload, upload_id, with_for_update=True)
    if upload is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Upload not found")
    if upload.status != UploadStatus.awaiting_approval:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Upload is {upload.status.value}, not waiting for approval"
        )
    return upload


@router.post("/{upload_id}/approve", response_model=UploadRead)
def approve_upload(upload_id: uuid.UUID, db: DbSession, admin: AdminUser) -> UploadRead:
    """Allow an upload over the size limit: it can now be sent (the uploader's open page carries on)."""
    upload = _awaiting(db, upload_id)
    upload.s3_upload_id = storage.create_multipart(
        get_settings().s3_bucket_raw, upload.staging_key, upload.content_type
    )
    upload.status = UploadStatus.uploading
    approvals.mark_reviewed(upload, admin.id)
    record_event(db, "upload.approved", f"Upload allowed: {upload.filename}", entity_type="upload", entity_id=upload.id,
                 actor_id=admin.id)  # fmt: skip
    db.commit()
    return _read(upload, _people(db, [upload]))


@router.post("/{upload_id}/reject", response_model=UploadRead)
def reject_upload(upload_id: uuid.UUID, body: UploadReview, db: DbSession, admin: AdminUser) -> UploadRead:
    """Turn down an upload over the size limit. Nothing of it was sent."""
    upload = _awaiting(db, upload_id)
    upload.status = UploadStatus.rejected
    upload.error = body.reason.strip() if body.reason and body.reason.strip() else "Rejected by the admin"
    approvals.mark_reviewed(upload, admin.id)
    record_event(db, "upload.rejected", f"Upload rejected: {upload.filename}", entity_type="upload", entity_id=upload.id,
                 actor_id=admin.id, data={"reason": upload.error})  # fmt: skip
    db.commit()
    return _read(upload, _people(db, [upload]))
