"""
Worker jobs for ingestion.

`ingest.upload`   staging object → SHA-256 → exact-duplicate check → content-addressed raw object →
                  ffprobe + decode check → video row (or `corrupt` flag). ZIPs are unpacked into their
                  videos, image sequences and sidecars; JSON/CSV sidecars are stored raw and parsed.
`ingest.derivatives`  raw video → 360p frame-exact proxy + thumbnail strip + frame index in the
                  derived bucket.
`video.frame_index`   (re)build the frame index from an existing proxy, for videos ingested before
                  the index existed.

Every step writes a job log line; nothing is estimated — values come from ffprobe or from the user.
"""

import hashlib
import json
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from egolabs import quality, storage
from egolabs.config import get_settings
from egolabs.events import record_event
from egolabs.ingest import frame_index
from egolabs.ingest.archive import ArchiveError, extract
from egolabs.ingest.formats import CONTENT_TYPES, SIDECAR_EXTENSIONS, extension
from egolabs.ingest.media import MediaError, make_proxy, make_thumbnail_strip
from egolabs.ingest.probe import ProbeError, decode_check, ffprobe_json, probe
from egolabs.ingest.sidecar import SidecarError, parse
from egolabs.jobs import enqueue_job
from egolabs.models import (
    LineageEdge,
    MetadataFile,
    Upload,
    UploadKind,
    UploadStatus,
    Video,
    VideoSource,
    VideoStatus,
)
from egolabs.worker.runtime import JobContext, job_handler


def raw_key(prefix: str, sha: str, ext: str = "") -> str:
    return f"{prefix}/{sha[:2]}/{sha}{ext}"


@dataclass
class UploadInfo:
    id: uuid.UUID
    kind: UploadKind
    filename: str
    staging_key: str
    session_id: uuid.UUID | None
    sequence_fps: float | None


@dataclass
class IngestResult:
    created: list[str] = field(default_factory=list)
    duplicates: list[dict[str, str]] = field(default_factory=list)
    corrupt: list[str] = field(default_factory=list)
    sidecars: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    stems: dict[str, str] = field(default_factory=dict)  # file stem → video id, to attach sidecars

    def summary(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("stems")
        return data


def _stem(name: str) -> str:
    return PurePosixPath(name).stem.lower()


def _lineage(db, parent_type: str, parent_id: uuid.UUID, child_type: str, child_id: uuid.UUID, relation: str,
             job_id: uuid.UUID) -> None:  # fmt: skip
    exists = db.scalar(
        select(LineageEdge.id).where(
            LineageEdge.parent_type == parent_type,
            LineageEdge.parent_id == parent_id,
            LineageEdge.child_type == child_type,
            LineageEdge.child_id == child_id,
            LineageEdge.relation == relation,
        )
    )
    if exists is None:
        db.add(
            LineageEdge(
                parent_type=parent_type, parent_id=parent_id, child_type=child_type, child_id=child_id,
                relation=relation, job_id=job_id,
            )
        )  # fmt: skip


def _record_duplicate(
    ctx: JobContext, up: UploadInfo, existing: Video, name: str, result: IngestResult
) -> None:
    ctx.info("Exact duplicate of an existing video; linked instead of stored", name=name,
             video_id=str(existing.id), sha256=existing.sha256)  # fmt: skip
    result.duplicates.append({"name": name, "video_id": str(existing.id)})
    result.stems[_stem(name)] = str(existing.id)
    with ctx.session() as db:
        _lineage(db, "upload", up.id, "video", existing.id, "duplicate_of", ctx.job_id)
        record_event(db, "video.duplicate", f"Duplicate upload linked to existing video: {name}",
                     entity_type="video", entity_id=existing.id, data={"upload_id": str(up.id)})  # fmt: skip
        db.commit()


def _insert_video(
    ctx: JobContext, up: UploadInfo, video: Video, name: str, result: IngestResult
) -> uuid.UUID | None:
    """Insert a video row; returns its id, or None if another upload stored the same content first."""
    with ctx.session() as db:
        db.add(video)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            existing = db.scalar(select(Video).where(Video.sha256 == video.sha256))
            if existing is None:
                raise
            _record_duplicate(ctx, up, existing, name, result)
            return None
        _lineage(db, "upload", up.id, "video", video.id, "ingested_as", ctx.job_id)
        if video.status == VideoStatus.corrupt:
            record_event(db, "video.corrupt", f"Unreadable video flagged: {name}", entity_type="video",
                         entity_id=video.id, data={"error": video.error})  # fmt: skip
        else:
            record_event(
                db, "video.ingested", f"Video ingested: {name}", entity_type="video", entity_id=video.id
            )
        db.commit()
        video_id = video.id
    result.stems[_stem(name)] = str(video_id)
    if video.status == VideoStatus.corrupt:
        result.corrupt.append(str(video_id))
    else:
        result.created.append(str(video_id))
        with ctx.session() as db:
            enqueue_job(db, "ingest.derivatives", {"video_id": str(video_id)}, parent_job_id=ctx.job_id)
    return video_id


def ingest_video_file(
    ctx: JobContext,
    up: UploadInfo,
    path: Path,
    sha: str,
    size: int,
    name: str,
    source_kind: VideoSource,
    source_path: str | None,
    result: IngestResult,
) -> None:
    with ctx.session() as db:
        existing = db.scalar(select(Video).where(Video.sha256 == sha))
    if existing is not None:
        _record_duplicate(ctx, up, existing, name, result)
        return

    error = None
    try:
        info = probe(path)
        decode_check(path)
    except ProbeError as exc:
        # Report the file by its uploaded name, not the worker's scratch path.
        info, error = None, str(exc).replace(str(path), PurePosixPath(name).name)
        ctx.warning("File is not readable video; flagged corrupt", name=name, error=error)
    else:
        ctx.info("Probed", name=name, codec=info.codec, width=info.width, height=info.height, fps=info.fps,
                 frame_count=info.frame_count, duration_s=info.duration_s)  # fmt: skip

    ext = extension(name)
    key = raw_key("videos", sha, ext)
    stored = storage.put_raw(path, key, CONTENT_TYPES.get(ext))
    ctx.info("Stored raw file" if stored else "Raw object already present", key=key, size_bytes=size)

    video = Video(
        session_id=up.session_id,
        original_filename=PurePosixPath(name).name,
        storage_key=key,
        sha256=sha,
        size_bytes=size,
        status=VideoStatus.corrupt if error else VideoStatus.processing,
        quality_flags=["corrupt"] if error else [],
        source_kind=source_kind,
        upload_id=up.id,
        source_path=source_path,
        error=error,
    )
    if info is not None:
        video.duration_s = info.duration_s
        video.width, video.height, video.fps = info.width, info.height, info.fps
        video.codec, video.frame_count, video.bit_rate = info.codec, info.frame_count, info.bit_rate
        video.has_audio = info.has_audio
        video.probe = info.raw
        video.camera_metadata = info.camera_metadata or None
    _insert_video(ctx, up, video, name, result)


def ingest_image_sequence(
    ctx: JobContext, up: UploadInfo, folder: str, frames: list[Path], archive_name: str, result: IngestResult
) -> None:
    exts = {extension(f.name) for f in frames}
    label = folder if folder not in ("", ".") else archive_name
    if len(exts) != 1:
        result.errors.append({"name": label, "error": f"mixed image formats in one sequence: {sorted(exts)}"})
        ctx.warning("Skipped image sequence with mixed formats", folder=label, formats=sorted(exts))
        return
    ext = exts.pop()
    frame_hashes = [storage.sha256_file(f) for f in frames]
    # Content address for the sequence: hash of the ordered frame hashes.
    sha = hashlib.sha256("\n".join(frame_hashes).encode()).hexdigest()
    with ctx.session() as db:
        existing = db.scalar(select(Video).where(Video.sha256 == sha))
    if existing is not None:
        _record_duplicate(ctx, up, existing, label, result)
        return

    error, first = None, None
    try:
        for frame in (frames[0], frames[-1]):
            data = ffprobe_json(frame)
            stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
            if stream is None:
                raise ProbeError(f"{frame.name}: not an image")
            first = first or stream
    except ProbeError as exc:
        error = str(exc)
        ctx.warning("Image sequence is not readable; flagged corrupt", folder=label, error=error)

    prefix = f"sequences/{sha[:2]}/{sha}/"
    for i, frame in enumerate(frames, start=1):
        storage.put_raw(frame, f"{prefix}{i:06d}{ext}", CONTENT_TYPES.get(ext))
    ctx.info("Stored image sequence frames", folder=label, frames=len(frames), key=prefix)

    fps = up.sequence_fps
    video = Video(
        session_id=up.session_id,
        original_filename=f"{PurePosixPath(archive_name).stem}/{label}"
        if label != archive_name
        else archive_name,
        storage_key=prefix,
        sha256=sha,
        size_bytes=sum(f.stat().st_size for f in frames),
        status=VideoStatus.corrupt if error else VideoStatus.processing,
        quality_flags=["corrupt"] if error else [],
        source_kind=VideoSource.image_sequence,
        upload_id=up.id,
        source_path=folder,
        frame_count=len(frames),
        fps=fps,  # user input only; unknown stays null
        duration_s=round(len(frames) / fps, 6) if fps else None,
        width=int(first["width"]) if first and first.get("width") else None,
        height=int(first["height"]) if first and first.get("height") else None,
        codec=first.get("codec_name") if first else None,
        has_audio=False,
        probe={"frames": len(frames), "first_frame": first} if first else None,
        error=error,
    )
    _insert_video(ctx, up, video, label, result)


def ingest_sidecar(
    ctx: JobContext, up: UploadInfo, path: Path, name: str, result: IngestResult, sha: str | None = None
) -> None:
    ext = extension(name)
    fmt = ext.lstrip(".")
    sha = sha or storage.sha256_file(path)
    key = raw_key("sidecars", sha, ext)
    storage.put_raw(path, key, CONTENT_TYPES.get(ext))
    parsed, error = None, None
    try:
        parsed = parse(path, fmt)
    except SidecarError as exc:
        error = str(exc)
        ctx.warning("Sidecar could not be parsed; stored raw", name=name, error=error)

    video_id = result.stems.get(_stem(name))
    with ctx.session() as db:
        if video_id is None and up.session_id is not None:
            # A standalone sidecar attaches to the session video with the same file name stem.
            candidates = db.scalars(select(Video).where(Video.session_id == up.session_id)).all()
            match = next((v for v in candidates if _stem(v.original_filename) == _stem(name)), None)
            video_id = str(match.id) if match else None
        sidecar = MetadataFile(
            upload_id=up.id,
            session_id=up.session_id,
            video_id=uuid.UUID(video_id) if video_id else None,
            filename=PurePosixPath(name).name,
            format=fmt,
            storage_key=key,
            sha256=sha,
            parsed=parsed,
            error=error,
        )
        db.add(sidecar)
        db.flush()
        _lineage(db, "upload", up.id, "metadata_file", sidecar.id, "ingested_as", ctx.job_id)
        db.commit()
        result.sidecars.append(str(sidecar.id))
    ctx.info("Stored sidecar", name=name, format=fmt, attached_to_video=video_id)


def _ingest_archive(
    ctx: JobContext, up: UploadInfo, path: Path, sha: str, work: Path, result: IngestResult
) -> None:
    key = raw_key("archives", sha, ".zip")
    storage.put_raw(path, key, "application/zip")
    ctx.info("Stored raw archive", key=key)
    members = work / "members"
    members.mkdir()
    contents = extract(path, members, get_settings().max_archive_uncompressed_bytes)
    ctx.info("Unpacked archive", videos=len(contents.videos), sequences=len(contents.sequences),
             sidecars=len(contents.sidecars), skipped=len(contents.skipped))  # fmt: skip
    result.skipped += contents.skipped
    for name, member in contents.videos:
        member_sha = storage.sha256_file(member)
        ingest_video_file(ctx, up, member, member_sha, member.stat().st_size, name, VideoSource.archive_member,
                          name, result)  # fmt: skip
        member.unlink()
    for folder, frames in contents.sequences:
        ingest_image_sequence(ctx, up, folder, frames, up.filename, result)
        for frame in frames:
            frame.unlink()
    for name, member in contents.sidecars:  # last, so they can attach to videos from the same archive
        ingest_sidecar(ctx, up, member, name, result)


def _finish(ctx: JobContext, up: UploadInfo, result: IngestResult) -> UploadStatus:
    if up.kind == UploadKind.video and result.duplicates and not (result.created or result.corrupt):
        status = UploadStatus.duplicate
    elif result.errors and not (result.created or result.corrupt or result.duplicates or result.sidecars):
        status = UploadStatus.failed
    else:
        status = UploadStatus.processed
    first = next(iter(result.created + result.corrupt + [d["video_id"] for d in result.duplicates]), None)
    with ctx.session() as db:
        row = db.get(Upload, up.id)
        assert row is not None
        row.status = status
        row.result = result.summary()
        row.video_id = uuid.UUID(first) if first else None
        if status == UploadStatus.failed:
            row.error = "; ".join(e["error"] for e in result.errors)[:2000]
        record_event(db, f"upload.{status.value}", f"Upload {status.value}: {up.filename}", entity_type="upload",
                     entity_id=up.id, data=result.summary())  # fmt: skip
        db.commit()
    return status


@job_handler("ingest.upload")
def ingest_upload(ctx: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    with ctx.session() as db:
        row = db.get(Upload, uuid.UUID(payload["upload_id"]))
        if row is None:
            raise LookupError(f"upload {payload['upload_id']} not found")
        up = UploadInfo(row.id, row.kind, row.filename, row.staging_key, row.session_id, row.sequence_fps)

    result = IngestResult()
    try:
        with tempfile.TemporaryDirectory(dir=settings.work_dir, prefix="egolabs-ingest-") as tmp:
            work = Path(tmp)
            source = work / f"upload{extension(up.filename)}"
            sha, size = storage.download_and_hash(settings.s3_bucket_raw, up.staging_key, source)
            ctx.info("Downloaded upload and computed checksum", sha256=sha, size_bytes=size)
            if up.kind == UploadKind.video:
                ingest_video_file(ctx, up, source, sha, size, up.filename, VideoSource.file, None, result)
            elif up.kind == UploadKind.archive:
                try:
                    _ingest_archive(ctx, up, source, sha, work, result)
                except ArchiveError as exc:
                    result.errors.append({"name": up.filename, "error": str(exc)})
                    ctx.log("error", "Archive rejected", error=str(exc))
            elif extension(up.filename) in SIDECAR_EXTENSIONS:
                ingest_sidecar(ctx, up, source, up.filename, result, sha=sha)
    except Exception as exc:
        with ctx.session() as db:
            row = db.get(Upload, up.id)
            if row is not None:
                row.status = UploadStatus.failed
                row.error = f"{type(exc).__name__}: {exc}"[:2000]
                row.result = result.summary()
                db.commit()
        raise

    status = _finish(ctx, up, result)
    try:
        storage.delete(settings.s3_bucket_raw, up.staging_key)  # the raw copy is now content-addressed
    except Exception as exc:  # leftover staging objects are harmless; log and move on
        ctx.warning("Could not delete staging object", key=up.staging_key, error=str(exc))
    return {"status": status.value, **result.summary()}


@job_handler("ingest.derivatives")
def ingest_derivatives(ctx: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    video_id = uuid.UUID(payload["video_id"])
    with ctx.session() as db:
        video = db.get(Video, video_id)
        if video is None:
            raise LookupError(f"video {video_id} not found")
        key, kind, fps = video.storage_key, video.source_kind, video.fps
        duration, frames, name = video.duration_s, video.frame_count, video.original_filename

    with tempfile.TemporaryDirectory(dir=settings.work_dir, prefix="egolabs-derive-") as tmp:
        work = Path(tmp)
        pattern = None
        if kind == VideoSource.image_sequence:
            source = work / "frames"
            source.mkdir()
            keys = storage.list_keys(settings.s3_bucket_raw, key)
            for k in keys:
                storage.download(settings.s3_bucket_raw, k, source / PurePosixPath(k).name)
            pattern = f"%06d{extension(keys[0])}"
        else:
            source = work / f"source{extension(key)}"
            storage.download(settings.s3_bucket_raw, key, source)
        ctx.info("Fetched raw media", key=key)

        proxy, strip = work / "proxy.mp4", work / "strip.jpg"
        try:
            proxy_meta = make_proxy(source, proxy, sequence_pattern=pattern, sequence_fps=fps)
            thumbs_meta = make_thumbnail_strip(
                source,
                strip,
                duration_s=duration,
                frame_count=frames,
                sequence_pattern=pattern,
                sequence_fps=fps,
            )
        except MediaError as exc:
            message = str(exc).replace(str(source), name)
            with ctx.session() as db:
                row = db.get(Video, video_id)
                assert row is not None
                row.status, row.error = VideoStatus.corrupt, message
                quality.refresh(db, row)
                record_event(db, "video.corrupt", f"Video failed to decode: {name}", entity_type="video",
                             entity_id=video_id, data={"error": message})  # fmt: skip
                db.commit()
            ctx.log("error", "Could not decode the full video; flagged corrupt", error=message)
            raise

        proxy_info = probe(proxy)
        proxy_meta.update(width=proxy_info.width, frame_count=proxy_info.frame_count, fps=proxy_info.fps)
        if frames is not None and proxy_info.frame_count != frames:
            ctx.warning("Proxy frame count differs from source", source=frames, proxy=proxy_info.frame_count)
        proxy_key, strip_key = f"proxies/{video_id}/proxy.mp4", f"thumbnails/{video_id}/strip.jpg"
        storage.upload(proxy, settings.s3_bucket_derived, proxy_key, "video/mp4")
        storage.upload(strip, settings.s3_bucket_derived, strip_key, "image/jpeg")
        ctx.info("Stored proxy and thumbnail strip", proxy_key=proxy_key, thumbnails_key=strip_key,
                 proxy_frames=proxy_info.frame_count)  # fmt: skip
        try:
            index_meta: dict[str, Any] | None = _store_frame_index(ctx, video_id, proxy)
        except frame_index.FrameIndexError as exc:
            # The proxy still plays; the inspector falls back to nominal FPS and says so.
            index_meta = None
            ctx.warning("Could not build the frame index", error=str(exc))

    with ctx.session() as db:
        row = db.get(Video, video_id)
        assert row is not None
        row.proxy_key, row.thumbnails_key = proxy_key, strip_key
        row.derivatives = {"proxy": proxy_meta, "thumbnails": thumbs_meta}
        if index_meta:
            row.derivatives["frame_index"] = index_meta
        row.status = VideoStatus.ready
        quality.refresh(db, row)
        record_event(db, "video.ready", f"Video ready: {name}", entity_type="video", entity_id=video_id)
        db.commit()
    auto_runs = _start_upload_pipelines(ctx, video_id)
    return {"proxy_key": proxy_key, "thumbnails_key": strip_key, "proxy_frames": proxy_info.frame_count,
            "frame_index": index_meta, "pipeline_runs": auto_runs}  # fmt: skip


def _start_upload_pipelines(ctx: JobContext, video_id: uuid.UUID) -> list[str]:
    """Pipelines marked to run on new uploads start on the ready video. Never fails the ingest: the video is
    ready either way, and a pipeline can still be run on it by hand."""
    from egolabs.pipelines import auto

    try:
        with ctx.session() as db:
            started = auto.start_for_video(db, video_id)
    except Exception as exc:
        ctx.warning(
            "Could not start the pipelines that run on new uploads", error=f"{type(exc).__name__}: {exc}"
        )
        return []
    for name, number in started:
        ctx.info("Started pipeline on the new upload", pipeline=name, run=number)
    return [f"{name} #{number}" for name, number in started]


def frame_index_key(video_id: uuid.UUID) -> str:
    return f"frame-index/{video_id}/index.json"


def _store_frame_index(ctx: JobContext, video_id: uuid.UUID, proxy: Path) -> dict[str, Any]:
    index = frame_index.build(proxy)
    key = frame_index_key(video_id)
    body = json.dumps(index, separators=(",", ":")).encode()
    storage.put_bytes(body, get_settings().s3_bucket_derived, key, "application/json")
    meta = frame_index.summary(index, key)
    ctx.info("Stored frame index", key=key, frame_count=index["frame_count"], runs=len(index["runs"]))
    return meta


@job_handler("video.frame_index")
def build_frame_index(ctx: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    video_id = uuid.UUID(payload["video_id"])
    with ctx.session() as db:
        video = db.get(Video, video_id)
        if video is None:
            raise LookupError(f"video {video_id} not found")
        if not video.proxy_key:
            raise LookupError("video has no proxy yet")
        proxy_key = video.proxy_key
    with tempfile.TemporaryDirectory(dir=settings.work_dir, prefix="egolabs-index-") as tmp:
        proxy = Path(tmp) / "proxy.mp4"
        storage.download(settings.s3_bucket_derived, proxy_key, proxy)
        meta = _store_frame_index(ctx, video_id, proxy)
    with ctx.session() as db:
        row = db.get(Video, video_id)
        assert row is not None
        row.derivatives = {**(row.derivatives or {}), "frame_index": meta}
        quality.refresh(db, row)
        db.commit()
    return meta
