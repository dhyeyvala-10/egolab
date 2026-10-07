"""
Datasets: session membership (Phase 1), and versions, rebuild checks, and exports (Phase 6).

A version is created from a spec (filters + split); its inputs are pinned when it is created and a worker job
builds it (`datasets.build_version`). Versions are immutable once ready. A check rebuilds a version from its
recorded spec and inputs and compares the hash (`datasets.verify_version`); an export writes one format
(`datasets.export`).
"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import delete, func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from egolabs import quality, storage
from egolabs.api.annotations import user_ref
from egolabs.api.deps import CurrentUser, DbSession, Processor, Writer
from egolabs.config import get_settings
from egolabs.datasets import build, lineage
from egolabs.events import record_event
from egolabs.jobs import enqueue_job
from egolabs.models import (
    BuildStatus,
    CaptureSession,
    Dataset,
    DatasetExport,
    DatasetVersion,
    DatasetVersionCheck,
    DatasetVersionSample,
    ExportFormat,
    ModelVersion,
    MovementEvent,
    User,
    Video,
    dataset_sessions,
)
from egolabs.schemas import Page
from egolabs.schemas.catalog import DatasetCreate, DatasetMembership, DatasetRead, DatasetSummary, Ref
from egolabs.schemas.cv import ModelVersionRef
from egolabs.schemas.datasets import (
    CheckRead,
    DatasetDetail,
    DatasetFacets,
    DatasetPreview,
    DatasetSpec,
    ExportCreate,
    ExportDownload,
    ExportRead,
    LineageGraph,
    QualityFlagInfo,
    SampleRead,
    VersionCounts,
    VersionCreate,
    VersionDetail,
    VersionSummary,
)

router = APIRouter(prefix="/datasets", tags=["datasets"])


@router.get("", response_model=Page[DatasetSummary])
def list_datasets(
    db: DbSession,
    _: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[DatasetSummary]:
    counts = (
        select(dataset_sessions.c.dataset_id.label("did"), func.count().label("n"))
        .group_by(dataset_sessions.c.dataset_id)
        .subquery()
    )
    versions = (
        select(
            DatasetVersion.dataset_id.label("did"),
            func.count().label("n"),
            func.max(DatasetVersion.number).label("last"),
        )
        .where(DatasetVersion.status == BuildStatus.ready)
        .group_by(DatasetVersion.dataset_id)
        .subquery()
    )
    stmt = (
        select(Dataset, func.coalesce(counts.c.n, 0), func.coalesce(versions.c.n, 0), versions.c.last)
        .outerjoin(counts, counts.c.did == Dataset.id)
        .outerjoin(versions, versions.c.did == Dataset.id)
    )
    total = db.scalar(select(func.count()).select_from(Dataset)) or 0
    rows = db.execute(stmt.order_by(Dataset.name).limit(limit).offset(offset)).all()
    items = [DatasetSummary(**DatasetRead.model_validate(d).model_dump(), session_count=n, version_count=vn,
                            latest_version=last) for d, n, vn, last in rows]  # fmt: skip
    return Page[DatasetSummary](items=items, total=total, limit=limit, offset=offset)


@router.post("", response_model=DatasetRead, status_code=status.HTTP_201_CREATED)
def create_dataset(body: DatasetCreate, db: DbSession, user: Writer) -> Dataset:
    dataset = Dataset(name=body.name, description=body.description, created_by=user.id)
    db.add(dataset)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"A dataset named {body.name!r} already exists"
        ) from exc
    record_event(db, "dataset.created", f"Dataset created: {body.name}", entity_type="dataset",
                 entity_id=dataset.id, actor_id=user.id)  # fmt: skip
    db.commit()
    return dataset


@router.post("/{dataset_id}/sessions", status_code=status.HTTP_204_NO_CONTENT)
def add_session(dataset_id: uuid.UUID, body: DatasetMembership, db: DbSession, user: Writer) -> Response:
    dataset = db.get(Dataset, dataset_id)
    session = db.get(CaptureSession, body.session_id)
    if dataset is None or session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dataset or session not found")
    exists = db.scalar(
        select(func.count())
        .select_from(dataset_sessions)
        .where(dataset_sessions.c.dataset_id == dataset_id, dataset_sessions.c.session_id == body.session_id)
    )
    if not exists:
        db.execute(insert(dataset_sessions).values(dataset_id=dataset_id, session_id=body.session_id))
        record_event(db, "dataset.session_added", f"{session.name} added to dataset {dataset.name}",
                     entity_type="dataset", entity_id=dataset.id, actor_id=user.id,
                     data={"session_id": str(session.id)})  # fmt: skip
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{dataset_id}/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_session(dataset_id: uuid.UUID, session_id: uuid.UUID, db: DbSession, user: Writer) -> Response:
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dataset not found")
    result = db.execute(
        delete(dataset_sessions).where(
            dataset_sessions.c.dataset_id == dataset_id, dataset_sessions.c.session_id == session_id
        )
    )
    if result.rowcount:
        record_event(db, "dataset.session_removed", f"Session removed from dataset {dataset.name}",
                     entity_type="dataset", entity_id=dataset.id, actor_id=user.id,
                     data={"session_id": str(session_id)})  # fmt: skip
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Phase 6: versions, checks, exports ---------------------------------------------------------------


def _users(db: Session, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, User]:
    wanted = {i for i in ids if i}
    return {u.id: u for u in db.scalars(select(User).where(User.id.in_(wanted)))} if wanted else {}


def _summary(v: DatasetVersion, dataset: Dataset, users: dict[uuid.UUID, User]) -> VersionSummary:
    return VersionSummary(id=v.id, dataset=Ref(id=dataset.id, name=dataset.name), number=v.number, status=v.status,
                          parent_version_id=v.parent_version_id, content_hash=v.content_hash, sample_count=v.sample_count,
                          counts=VersionCounts.model_validate(v.counts or {}), created_at=v.created_at,
                          built_at=v.built_at, created_by=user_ref(users.get(v.created_by)) if v.created_by else None,
                          error=v.error, note=v.note)  # fmt: skip


def _version(db: Session, version_id: uuid.UUID) -> DatasetVersion:
    v = db.get(DatasetVersion, version_id)
    if v is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dataset version not found")
    return v


def _export_read(e: DatasetExport, v: DatasetVersion, d: Dataset) -> ExportRead:
    return ExportRead(id=e.id, version_id=v.id, dataset=Ref(id=d.id, name=d.name), version_number=v.number,
                      format=e.format, status=e.status, size_bytes=e.size_bytes, sha256=e.sha256, files=e.files,
                      created_at=e.created_at, finished_at=e.finished_at, error=e.error, job_id=e.job_id)  # fmt: skip


@router.get("/facets", response_model=DatasetFacets)
def facets(db: DbSession, _: CurrentUser) -> DatasetFacets:
    """What the builder can filter on: environments, object labels, and quality flags with video counts."""
    envs = sorted(e for (e,) in db.execute(select(CaptureSession.environment).distinct()) if e)
    objects = sorted(o for (o,) in db.execute(select(MovementEvent.object_label).distinct()) if o)
    flag_counts = dict(db.execute(select(func.unnest(Video.quality_flags).label("f"), func.count()).group_by("f")).tuples().all())  # fmt: skip
    flags = [
        QualityFlagInfo(flag=f, description=d, videos=flag_counts.get(f, 0))
        for f, d in {**quality.FLAGS, **quality.CHECK_FLAGS}.items()
    ]
    flags += [
        QualityFlagInfo(flag=f, description="", videos=n)
        for f, n in sorted(flag_counts.items())
        if f not in quality.FLAGS and f not in quality.CHECK_FLAGS
    ]
    return DatasetFacets(
        environments=envs, object_labels=objects, quality_flags=flags, formats=list(ExportFormat)
    )


@router.post("/preview", response_model=DatasetPreview)
def preview(body: DatasetSpec, db: DbSession, _: CurrentUser) -> DatasetPreview:
    """What a version with this spec would contain if built now (counts, split balance, a sample). Stores nothing."""
    return DatasetPreview.model_validate(build.preview(db, body))


@router.get("/versions", response_model=Page[VersionSummary])
def list_versions(
    db: DbSession,
    _: CurrentUser,
    dataset_id: uuid.UUID | None = None,
    status_: Annotated[list[BuildStatus] | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[VersionSummary]:
    stmt = select(DatasetVersion, Dataset).join(Dataset, Dataset.id == DatasetVersion.dataset_id)
    if dataset_id:
        stmt = stmt.where(DatasetVersion.dataset_id == dataset_id)
    if status_:
        stmt = stmt.where(DatasetVersion.status.in_(status_))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(
        stmt.order_by(DatasetVersion.created_at.desc(), DatasetVersion.id).limit(limit).offset(offset)
    ).all()
    users = _users(db, {v.created_by for v, _d in rows})
    return Page[VersionSummary](
        items=[_summary(v, d, users) for v, d in rows], total=total, limit=limit, offset=offset
    )


@router.get("/versions/{version_id}", response_model=VersionDetail)
def get_version(version_id: uuid.UUID, db: DbSession, _: CurrentUser) -> VersionDetail:
    v = _version(db, version_id)
    d = db.get(Dataset, v.dataset_id)
    assert d is not None
    mvs = (
        db.scalars(select(ModelVersion).where(ModelVersion.id.in_(v.model_version_ids))).all()
        if v.model_version_ids
        else []
    )
    return VersionDetail(**_summary(v, d, _users(db, {v.created_by})).model_dump(),
                         spec=DatasetSpec.model_validate(v.spec), inputs=v.inputs,
                         model_versions=[ModelVersionRef.model_validate(m) for m in mvs], job_id=v.job_id)  # fmt: skip


@router.get("/versions/{version_id}/samples", response_model=Page[SampleRead])
def version_samples(
    version_id: uuid.UUID,
    db: DbSession,
    _: CurrentUser,
    split: Literal["train", "val", "test"] | None = None,
    class_: Annotated[str | None, Query(alias="class", max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[SampleRead]:
    _version(db, version_id)
    stmt = select(DatasetVersionSample).where(DatasetVersionSample.version_id == version_id)
    if split:
        stmt = stmt.where(DatasetVersionSample.split == split)
    if class_:
        stmt = stmt.where(DatasetVersionSample.class_name == class_)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(DatasetVersionSample.sample_no).limit(limit).offset(offset)).all()
    return Page[SampleRead](
        items=[SampleRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset
    )


@router.get("/samples/{sample_id}", response_model=SampleRead)
def get_sample(sample_id: uuid.UUID, db: DbSession, _: CurrentUser) -> SampleRead:
    s = db.get(DatasetVersionSample, sample_id)
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sample not found")
    return SampleRead.model_validate(s)


@router.get("/samples/{sample_id}/lineage", response_model=LineageGraph)
def sample_lineage(sample_id: uuid.UUID, db: DbSession, _: CurrentUser) -> LineageGraph:
    """Trace a sample back through its annotation, event, model runs and versions, jobs, video, and raw file."""
    s = db.get(DatasetVersionSample, sample_id)
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sample not found")
    return LineageGraph.model_validate(lineage.sample_graph(db, s))


@router.post("/versions/{version_id}/checks", response_model=CheckRead, status_code=status.HTTP_202_ACCEPTED)
def check_version(version_id: uuid.UUID, db: DbSession, user: Processor) -> DatasetVersionCheck:
    """Rebuild the version from its recorded spec and inputs, and compare the content hash (a worker job)."""
    v = _version(db, version_id)
    if v.status != BuildStatus.ready:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Version is {v.status.value}; only a ready version can be checked"
        )
    check = DatasetVersionCheck(version_id=v.id, created_by=user.id)
    db.add(check)
    db.commit()
    job = enqueue_job(db, "datasets.verify_version", {"check_id": str(check.id)}, created_by=user.id)
    check.job_id = job.id
    db.commit()
    return check


@router.get("/versions/{version_id}/checks", response_model=list[CheckRead])
def list_checks(version_id: uuid.UUID, db: DbSession, _: CurrentUser) -> list[DatasetVersionCheck]:
    _version(db, version_id)
    return list(db.scalars(select(DatasetVersionCheck).where(DatasetVersionCheck.version_id == version_id)
                           .order_by(DatasetVersionCheck.created_at.desc()).limit(50)))  # fmt: skip


@router.post(
    "/versions/{version_id}/exports", response_model=ExportRead, status_code=status.HTTP_202_ACCEPTED
)
def create_export(version_id: uuid.UUID, body: ExportCreate, db: DbSession, user: Processor) -> ExportRead:
    """Write the version out in one format (a worker job); download it when ready."""
    v = _version(db, version_id)
    if v.status != BuildStatus.ready:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Version is {v.status.value}; only a ready version can be exported"
        )
    d = db.get(Dataset, v.dataset_id)
    assert d is not None
    ex = DatasetExport(version_id=v.id, format=body.format, created_by=user.id)
    db.add(ex)
    db.commit()
    job = enqueue_job(db, "datasets.export", {"export_id": str(ex.id)}, created_by=user.id)
    ex.job_id = job.id
    db.commit()
    return _export_read(ex, v, d)


@router.get("/exports", response_model=Page[ExportRead])
def list_exports(
    db: DbSession,
    _: CurrentUser,
    version_id: uuid.UUID | None = None,
    status_: Annotated[list[BuildStatus] | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ExportRead]:
    stmt = (select(DatasetExport, DatasetVersion, Dataset).join(DatasetVersion, DatasetVersion.id == DatasetExport.version_id)
            .join(Dataset, Dataset.id == DatasetVersion.dataset_id))  # fmt: skip
    if version_id:
        stmt = stmt.where(DatasetExport.version_id == version_id)
    if status_:
        stmt = stmt.where(DatasetExport.status.in_(status_))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(
        stmt.order_by(DatasetExport.created_at.desc(), DatasetExport.id).limit(limit).offset(offset)
    ).all()
    return Page[ExportRead](
        items=[_export_read(e, v, d) for e, v, d in rows], total=total, limit=limit, offset=offset
    )


@router.get("/exports/{export_id}/download", response_model=ExportDownload)
def download_export(export_id: uuid.UUID, db: DbSession, _: CurrentUser) -> ExportDownload:
    """A short-lived link to the export's zip, straight from storage."""
    e = db.get(DatasetExport, export_id)
    if e is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Export not found")
    if e.status != BuildStatus.ready or not e.storage_key:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Export is {e.status.value}")
    expires = 900
    return ExportDownload(url=storage.presign_get(get_settings().s3_bucket_derived, e.storage_key, expires),
                          filename=e.storage_key.rsplit("/", 1)[-1], expires_s=expires)  # fmt: skip


@router.get("/{dataset_id}", response_model=DatasetDetail)
def get_dataset(dataset_id: uuid.UUID, db: DbSession, _: CurrentUser) -> DatasetDetail:
    d = db.get(Dataset, dataset_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dataset not found")
    sessions = db.execute(select(CaptureSession.id, CaptureSession.name).join(
        dataset_sessions, dataset_sessions.c.session_id == CaptureSession.id).where(
        dataset_sessions.c.dataset_id == dataset_id).order_by(CaptureSession.name)).all()  # fmt: skip
    n, last = db.execute(select(func.count(), func.max(DatasetVersion.number)).where(
        DatasetVersion.dataset_id == dataset_id, DatasetVersion.status == BuildStatus.ready)).one()  # fmt: skip
    return DatasetDetail(id=d.id, name=d.name, description=d.description, created_at=d.created_at,
                         sessions=[Ref(id=i, name=nm) for i, nm in sessions], versions=n, latest_version=last)  # fmt: skip


@router.post("/{dataset_id}/versions", response_model=VersionSummary, status_code=status.HTTP_202_ACCEPTED)
def create_version(
    dataset_id: uuid.UUID, body: VersionCreate, db: DbSession, user: Processor
) -> VersionSummary:
    """
    Create the next version: its inputs (videos, runs, as_of) are pinned now, and a worker builds it. The
    version is immutable once ready.
    """
    d = db.get(Dataset, dataset_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dataset not found")
    v = build.create_version(db, d, body.spec, user.id, body.note)
    if not v.inputs["runs"]:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "No classified videos match these filters; nothing to build a version from")  # fmt: skip
    db.commit()
    job = enqueue_job(db, "datasets.build_version", {"version_id": str(v.id)}, created_by=user.id)
    v.job_id = job.id
    db.commit()
    return _summary(v, d, _users(db, {user.id}))
