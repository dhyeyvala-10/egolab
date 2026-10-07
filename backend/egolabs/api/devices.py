import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from egolabs.api.deps import CurrentUser, DbSession, Writer
from egolabs.models import CaptureSession, Device, Operator, Video
from egolabs.schemas import Page
from egolabs.schemas.catalog import (
    DeviceCreate,
    DeviceRead,
    DeviceSummary,
    DeviceUpdate,
    OperatorCreate,
    OperatorRead,
)

router = APIRouter(tags=["devices"])


@router.get("/devices", response_model=Page[DeviceSummary])
def list_devices(
    db: DbSession,
    _: CurrentUser,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[DeviceSummary]:
    sessions = (
        select(CaptureSession.device_id.label("did"), func.count().label("n"))
        .group_by(CaptureSession.device_id)
        .subquery()
    )
    videos = (
        select(CaptureSession.device_id.label("did"), func.count(Video.id).label("n"))
        .join(Video, Video.session_id == CaptureSession.id)
        .group_by(CaptureSession.device_id)
        .subquery()
    )
    stmt = (
        select(Device, func.coalesce(sessions.c.n, 0), func.coalesce(videos.c.n, 0))
        .outerjoin(sessions, sessions.c.did == Device.id)
        .outerjoin(videos, videos.c.did == Device.id)
    )
    if q:
        stmt = stmt.where(
            Device.name.ilike(f"%{q}%") | Device.kind.ilike(f"%{q}%") | Device.serial.ilike(f"%{q}%")
        )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(stmt.order_by(Device.name).limit(limit).offset(offset)).all()
    items = [
        DeviceSummary(**DeviceRead.model_validate(d).model_dump(), session_count=s, video_count=v)
        for d, s, v in rows
    ]
    return Page[DeviceSummary](items=items, total=total, limit=limit, offset=offset)


@router.post("/devices", response_model=DeviceRead, status_code=status.HTTP_201_CREATED)
def create_device(body: DeviceCreate, db: DbSession, _: Writer) -> Device:
    device = Device(name=body.name, kind=body.kind, serial=body.serial, metadata_=body.metadata)
    db.add(device)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, f"A device named {body.name!r} already exists") from exc
    return device


@router.patch("/devices/{device_id}", response_model=DeviceRead)
def update_device(device_id: uuid.UUID, body: DeviceUpdate, db: DbSession, _: Writer) -> Device:
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Device not found")
    for key, value in body.model_dump(exclude_unset=True).items():
        if key == "metadata":
            device.metadata_ = value or {}
        elif key == "name" and value is None:
            continue
        else:
            setattr(device, key, value)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "A device with that name already exists") from exc
    return device


@router.get("/operators", response_model=Page[OperatorRead])
def list_operators(
    db: DbSession,
    _: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[OperatorRead]:
    total = db.scalar(select(func.count()).select_from(Operator)) or 0
    rows = db.scalars(select(Operator).order_by(Operator.name, Operator.id).limit(limit).offset(offset)).all()
    return Page[OperatorRead](
        items=[OperatorRead.model_validate(o) for o in rows], total=total, limit=limit, offset=offset
    )


@router.post("/operators", response_model=OperatorRead, status_code=status.HTTP_201_CREATED)
def create_operator(body: OperatorCreate, db: DbSession, _: Writer) -> Operator:
    operator = Operator(name=body.name, external_id=body.external_id, notes=body.notes)
    db.add(operator)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "An operator with that external ID already exists"
        ) from exc
    return operator
