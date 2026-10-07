import json
import uuid
from typing import Annotated, Literal

from botocore.exceptions import ClientError
from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import selectinload

from egolabs import storage
from egolabs.api.deps import CurrentUser, DbSession, Writer
from egolabs.config import get_settings
from egolabs.events import record_event
from egolabs.jobs import enqueue_job
from egolabs.models import (
    CaptureSession,
    LineageEdge,
    MetadataFile,
    MovementEvent,
    Video,
    VideoSource,
    VideoStatus,
)
from egolabs.schemas import Page
from egolabs.schemas.annotation import FrameIndex, JobRef
from egolabs.schemas.catalog import LineageRef, Ref, SidecarRead, VideoDetail, VideoSummary, VideoUpdate

router = APIRouter(prefix="/videos", tags=["videos"])

SortKey = Literal[
    "created_at", "original_filename", "duration_s", "size_bytes", "width", "fps", "frame_count"
]


def _summary(video: Video) -> dict:
    data = VideoSummary.model_validate(
        {
            **{
                c: getattr(video, c)
                for c in VideoSummary.model_fields
                if hasattr(video, c) and c != "session"
            },
            "session": Ref(id=video.session.id, name=video.session.name) if video.session else None,
        }
    ).model_dump()
    if video.thumbnails_key:
        data["thumbnails_url"] = storage.presign_get(get_settings().s3_bucket_derived, video.thumbnails_key)
    return data


@router.get("", response_model=Page[VideoSummary])
def list_videos(
    db: DbSession,
    _: CurrentUser,
    q: Annotated[str | None, Query(max_length=200)] = None,
    session_id: uuid.UUID | None = None,
    unassigned: bool = False,
    status_: Annotated[VideoStatus | None, Query(alias="status")] = None,
    source_kind: VideoSource | None = None,
    codec: Annotated[str | None, Query(max_length=64)] = None,
    sort: SortKey = "created_at",
    order: Literal["asc", "desc"] = "desc",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[VideoSummary]:
    stmt = select(Video)
    if q:
        stmt = stmt.where(Video.original_filename.ilike(f"%{q}%"))
    if session_id:
        stmt = stmt.where(Video.session_id == session_id)
    if unassigned:
        stmt = stmt.where(Video.session_id.is_(None))
    if status_:
        stmt = stmt.where(Video.status == status_)
    if source_kind:
        stmt = stmt.where(Video.source_kind == source_kind)
    if codec:
        stmt = stmt.where(Video.codec == codec)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    column = getattr(Video, sort)
    direction = column.asc().nulls_last() if order == "asc" else column.desc().nulls_last()
    rows = db.scalars(
        stmt.options(selectinload(Video.session)).order_by(direction, Video.id).limit(limit).offset(offset)
    ).all()
    return Page[VideoSummary](
        items=[VideoSummary(**_summary(v)) for v in rows], total=total, limit=limit, offset=offset
    )


def _detail(db: DbSession, video_id: uuid.UUID) -> VideoDetail:
    video = db.get(Video, video_id, options=[selectinload(Video.session)])
    if video is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Video not found")
    sidecars = db.scalars(
        select(MetadataFile).where(MetadataFile.video_id == video_id).order_by(MetadataFile.created_at)
    ).all()
    edges = db.scalars(
        select(LineageEdge)
        .where(LineageEdge.child_type == "video", LineageEdge.child_id == video_id)
        .order_by(LineageEdge.created_at)
    ).all()
    detail = VideoDetail(
        **_summary(video),
        sha256=video.sha256,
        storage_key=video.storage_key,
        source_path=video.source_path,
        bit_rate=video.bit_rate,
        upload_id=video.upload_id,
        probe=video.probe,
        camera_metadata=video.camera_metadata,
        derivatives=video.derivatives or {},
        sidecars=[SidecarRead.model_validate(s) for s in sidecars],
        lineage=[
            LineageRef(
                parent_type=e.parent_type,
                parent_id=e.parent_id,
                relation=e.relation,
                job_id=e.job_id,
                created_at=e.created_at,
            )
            for e in edges
        ],  # fmt: skip
    )
    if video.proxy_key:
        detail.proxy_url = storage.presign_get(get_settings().s3_bucket_derived, video.proxy_key)
    return detail


@router.get("/{video_id}", response_model=VideoDetail)
def get_video(video_id: uuid.UUID, db: DbSession, _: CurrentUser) -> VideoDetail:
    return _detail(db, video_id)


@router.patch("/{video_id}", response_model=VideoDetail)
def update_video(video_id: uuid.UUID, body: VideoUpdate, db: DbSession, user: Writer) -> VideoDetail:
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Video not found")
    if "session_id" in body.model_fields_set:
        if body.session_id and db.get(CaptureSession, body.session_id) is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Session not found")
        if body.session_id != video.session_id:
            record_event(db, "video.session_changed", f"{video.original_filename} moved to another session",
                         entity_type="video", entity_id=video.id, actor_id=user.id,
                         data={"from": str(video.session_id) if video.session_id else None,
                               "to": str(body.session_id) if body.session_id else None})  # fmt: skip
            video.session_id = body.session_id
            # Movement events carry their video's session (for review and dataset filters): keep it in step.
            db.execute(
                update(MovementEvent)
                .where(MovementEvent.video_id == video.id)
                .values(session_id=body.session_id)
            )
    db.commit()
    return _detail(db, video_id)


@router.get(
    "/{video_id}/frame-index",
    response_model=FrameIndex,
    responses={404: {"description": "Video not found, or its frame index is not built yet"}},
)
def get_frame_index(video_id: uuid.UUID, db: DbSession, _: CurrentUser) -> Response:
    """Presentation timestamp of every proxy frame (run-length encoded), for frame-exact seeking."""
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Video not found")
    meta = (video.derivatives or {}).get("frame_index")
    if not meta:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Frame index not built")
    try:
        body = storage.get_bytes(get_settings().s3_bucket_derived, meta["key"])
    except ClientError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Frame index not built") from exc
    FrameIndex.model_validate(json.loads(body))  # never serve a malformed index
    return Response(
        content=body, media_type="application/json", headers={"Cache-Control": "private, max-age=300"}
    )


@router.post("/{video_id}/frame-index", response_model=JobRef, status_code=202)
def rebuild_frame_index(video_id: uuid.UUID, db: DbSession, user: Writer) -> JobRef:
    """Build the frame index from the stored proxy (for videos ingested before it existed)."""
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Video not found")
    if not video.proxy_key:
        raise HTTPException(status.HTTP_409_CONFLICT, "Video has no proxy yet")
    job = enqueue_job(db, "video.frame_index", {"video_id": str(video_id)}, created_by=user.id)
    return JobRef(job_id=job.id)
