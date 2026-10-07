"""Pipelines API (spec Phase 7): definitions and versions, templates, runs, step retries, run logs, schedules,
plus each video's quality checks and annotated videos."""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, literal_column, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from egolabs import storage
from egolabs.api.deps import CurrentUser, DbSession, Processor
from egolabs.config import get_settings
from egolabs.jobs import enqueue_job
from egolabs.models import (
    AnnotatedVideo,
    BuildStatus,
    CvRunKind,
    JobLog,
    LogLevel,
    Pipeline,
    PipelineRun,
    PipelineRunStatus,
    PipelineSchedule,
    PipelineStepAttempt,
    PipelineStepRun,
    PipelineVersion,
    RunTrigger,
    StepStatus,
    User,
    Video,
    VideoQualityCheck,
)
from egolabs.models.jobs import search_text
from egolabs.pipelines import cron, engine, inputs, schedules, templates
from egolabs.pipelines.graph import GraphError, auto_layout, graph_hash, validate
from egolabs.pipelines.steps import STEPS
from egolabs.schemas import Page
from egolabs.schemas.annotation import UserRef
from egolabs.schemas.catalog import Ref
from egolabs.schemas.pipelines import (
    AnnotatedVideoCreate,
    AnnotatedVideoRead,
    AttemptRead,
    CronPreview,
    CronPreviewIn,
    Download,
    GraphCheck,
    GraphIn,
    NodeProgress,
    PipelineCreate,
    PipelineDetail,
    PipelineSummary,
    PipelineUpdate,
    QualityCheckRead,
    RetryIn,
    RetryResult,
    RunBrief,
    RunCreate,
    RunDetail,
    RunLogLine,
    RunLogPage,
    RunSummary,
    ScheduleCreate,
    ScheduleRead,
    ScheduleUpdate,
    StepRead,
    StepTypeRead,
    TemplateRead,
    VersionBrief,
    VersionRead,
    VideoQuality,
)

router = APIRouter(prefix="/pipelines", tags=["pipelines"])
videos_router = APIRouter(tags=["pipelines"])
MATCH_CAP = 100_000


def _users(db: Session, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, UserRef]:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    return {
        u.id: UserRef(id=u.id, name=u.name or u.email)
        for u in db.scalars(select(User).where(User.id.in_(wanted)))
    }


def _checked(graph: GraphIn | dict[str, Any]) -> dict[str, Any]:
    raw = graph.model_dump() if isinstance(graph, GraphIn) else graph
    try:
        return validate(raw)
    except GraphError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, {"message": "The pipeline isn't valid",
                                                                     "errors": exc.errors}) from exc  # fmt: skip


def _pipeline(db: Session, pipeline_id: uuid.UUID) -> Pipeline:
    p = db.get(Pipeline, pipeline_id)
    if p is None or p.archived_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pipeline not found")
    return p


def _latest(db: Session, pipeline_id: uuid.UUID) -> PipelineVersion:
    v = schedules.latest_version(db, pipeline_id)
    assert v is not None
    return v


def _brief(run: PipelineRun | None) -> RunBrief | None:
    return (
        RunBrief(id=run.id, number=run.number, status=run.status, created_at=run.created_at) if run else None
    )


def _summaries(db: Session, rows: list[Pipeline]) -> list[PipelineSummary]:
    ids = [p.id for p in rows]
    if not ids:
        return []
    latest = {v.pipeline_id: v for v in db.scalars(
        select(PipelineVersion).where(PipelineVersion.pipeline_id.in_(ids))
        .distinct(PipelineVersion.pipeline_id).order_by(PipelineVersion.pipeline_id, PipelineVersion.number.desc()))}  # fmt: skip
    runs = dict(db.execute(select(PipelineRun.pipeline_id, func.count()).where(PipelineRun.pipeline_id.in_(ids))
                           .group_by(PipelineRun.pipeline_id)).tuples().all())  # fmt: skip
    last = {r.pipeline_id: r for r in db.scalars(
        select(PipelineRun).where(PipelineRun.pipeline_id.in_(ids)).distinct(PipelineRun.pipeline_id)
        .order_by(PipelineRun.pipeline_id, PipelineRun.number.desc()))}  # fmt: skip
    scheds = dict(db.execute(select(PipelineSchedule.pipeline_id, func.count()).where(PipelineSchedule.pipeline_id.in_(ids))
                             .group_by(PipelineSchedule.pipeline_id)).tuples().all())  # fmt: skip
    return [PipelineSummary(id=p.id, name=p.name, description=p.description, is_template=p.is_template,
                            run_on_upload=p.run_on_upload,
                            latest_version=latest[p.id].number, step_count=len(latest[p.id].graph["nodes"]),
                            run_count=runs.get(p.id, 0), last_run=_brief(last.get(p.id)),
                            schedule_count=scheds.get(p.id, 0), created_at=p.created_at, updated_at=p.updated_at)
            for p in rows if p.id in latest]  # fmt: skip


def _version_read(v: PipelineVersion, users: dict[uuid.UUID, UserRef]) -> VersionRead:
    return VersionRead(id=v.id, number=v.number, note=v.note, created_at=v.created_at,
                       created_by=users.get(v.created_by) if v.created_by else None, graph=v.graph,
                       graph_hash=v.graph_hash, parent_version_id=v.parent_version_id)  # fmt: skip


def _detail(db: Session, p: Pipeline) -> PipelineDetail:
    versions = list(db.scalars(select(PipelineVersion).where(PipelineVersion.pipeline_id == p.id)
                               .order_by(PipelineVersion.number.desc())))  # fmt: skip
    users = _users(db, {v.created_by for v in versions})
    (summary,) = _summaries(db, [p])
    return PipelineDetail(**summary.model_dump(), layout=p.layout or {}, version=_version_read(versions[0], users),
                          versions=[VersionBrief(id=v.id, number=v.number, note=v.note, created_at=v.created_at,
                                                 created_by=users.get(v.created_by) if v.created_by else None)
                                    for v in versions])  # fmt: skip


# --- catalogue -----------------------------------------------------------------------------------------


@router.get("/steps", response_model=list[StepTypeRead])
def step_types(_: CurrentUser) -> list[StepTypeRead]:
    """Every step a pipeline can use, with its settings (JSON schema and defaults)."""
    out = []
    for s in STEPS.values():
        defaults = s.config.model_validate(
            {"dataset": "Dataset"} if s.key == "dataset_build" else {}
        ).model_dump(mode="json")
        if s.key == "dataset_build":
            defaults["dataset"] = ""
        out.append(StepTypeRead(key=s.key, label=s.label, category=s.category, per_video=s.per_video,
                                description=s.description, requires=list(s.requires), uses=list(s.uses),
                                defaults=defaults, config_schema=s.config.model_json_schema()))  # fmt: skip
    return out


@router.get("/templates", response_model=list[TemplateRead])
def list_templates(_: CurrentUser) -> list[dict[str, Any]]:
    """The built-in starting points. Saved templates are pipelines with `is_template`."""
    return templates.templates()


@router.post("/validate", response_model=GraphCheck)
def validate_graph(body: GraphIn, _: CurrentUser) -> GraphCheck:
    try:
        return GraphCheck(ok=True, errors=[], graph=validate(body.model_dump()))
    except GraphError as exc:
        return GraphCheck(ok=False, errors=exc.errors, graph=None)  # type: ignore[arg-type]


@router.post("/schedules/preview", response_model=CronPreview)
def preview_cron(body: CronPreviewIn, _: CurrentUser) -> CronPreview:
    """The next five times a cron expression fires in a time zone."""
    try:
        return CronPreview(
            ok=True, error=None, upcoming=cron.upcoming(body.cron, body.timezone, datetime.now(UTC))
        )
    except cron.CronError as exc:
        return CronPreview(ok=False, error=str(exc), upcoming=[])


# --- runs ----------------------------------------------------------------------------------------------


def _counts(db: Session, run_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, int]]:
    out: dict[uuid.UUID, dict[str, int]] = {r: {} for r in run_ids}
    if run_ids:
        for rid, st, n in db.execute(select(PipelineStepRun.run_id, PipelineStepRun.status, func.count())
                                     .where(PipelineStepRun.run_id.in_(run_ids))
                                     .group_by(PipelineStepRun.run_id, PipelineStepRun.status)):  # fmt: skip
            out[rid][StepStatus(st).value] = n
    return out


def _run_summaries(db: Session, runs: list[PipelineRun]) -> list[RunSummary]:
    pipes = {
        p.id: p for p in db.scalars(select(Pipeline).where(Pipeline.id.in_({r.pipeline_id for r in runs})))
    }
    versions = dict(db.execute(select(PipelineVersion.id, PipelineVersion.number)
                               .where(PipelineVersion.id.in_({r.version_id for r in runs}))).tuples().all())  # fmt: skip
    counts = _counts(db, [r.id for r in runs])
    users = _users(db, {r.created_by for r in runs})
    out = []
    for r in runs:
        end = r.finished_at or (datetime.now(UTC) if r.status == PipelineRunStatus.running else None)
        out.append(RunSummary(id=r.id, number=r.number, pipeline=Ref(id=r.pipeline_id, name=pipes[r.pipeline_id].name),
                              version=versions[r.version_id], status=r.status, trigger=r.trigger,
                              schedule_id=r.schedule_id, video_count=r.video_count,
                              inputs_label=inputs.describe((r.inputs or {}).get("selector") or {}), counts=counts[r.id],
                              created_at=r.created_at, started_at=r.started_at, finished_at=r.finished_at,
                              duration_s=round((end - r.started_at).total_seconds(), 2) if end and r.started_at else None,
                              error=r.error, created_by=users.get(r.created_by) if r.created_by else None,
                              job_id=r.job_id))  # fmt: skip
    return out


def _run(db: Session, run_id: uuid.UUID) -> PipelineRun:
    r = db.get(PipelineRun, run_id)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    return r


@router.get("/runs", response_model=Page[RunSummary])
def list_runs(
    db: DbSession,
    _: CurrentUser,
    pipeline_id: uuid.UUID | None = None,
    schedule_id: uuid.UUID | None = None,
    status_: Annotated[list[PipelineRunStatus] | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[RunSummary]:
    stmt = select(PipelineRun)
    if pipeline_id:
        stmt = stmt.where(PipelineRun.pipeline_id == pipeline_id)
    if schedule_id:
        stmt = stmt.where(PipelineRun.schedule_id == schedule_id)
    if status_:
        stmt = stmt.where(PipelineRun.status.in_(status_))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    runs = list(
        db.scalars(stmt.order_by(PipelineRun.created_at.desc(), PipelineRun.id).limit(limit).offset(offset))
    )
    return Page[RunSummary](items=_run_summaries(db, runs), total=total, limit=limit, offset=offset)


@router.get("/runs/{run_id}", response_model=RunDetail)
def get_run(run_id: uuid.UUID, db: DbSession, _: CurrentUser) -> RunDetail:
    r = _run(db, run_id)
    (summary,) = _run_summaries(db, [r])
    version = db.get(PipelineVersion, r.version_id)
    pipeline = db.get(Pipeline, r.pipeline_id)
    assert version is not None and pipeline is not None
    by_node: dict[str, dict[str, int]] = {}
    for node, st, n in db.execute(select(PipelineStepRun.node_id, PipelineStepRun.status, func.count())
                                  .where(PipelineStepRun.run_id == r.id)
                                  .group_by(PipelineStepRun.node_id, PipelineStepRun.status)):  # fmt: skip
        by_node.setdefault(node, {})[StepStatus(st).value] = n
    stats = {node: (int(a or 0), float(s or 0)) for node, a, s in db.execute(
        select(PipelineStepRun.node_id, func.sum(PipelineStepRun.attempts),
               func.sum(func.extract("epoch", PipelineStepAttempt.finished_at - PipelineStepAttempt.started_at)))
        .outerjoin(PipelineStepAttempt, PipelineStepAttempt.step_run_id == PipelineStepRun.id)
        .where(PipelineStepRun.run_id == r.id).group_by(PipelineStepRun.node_id))}  # fmt: skip
    nodes = []
    for n in version.graph["nodes"]:
        step = STEPS.get(n["type"])
        attempts, seconds = stats.get(n["id"], (0, 0.0))
        nodes.append(NodeProgress(node_id=n["id"], step_type=n["type"], label=step.label if step else n["type"],
                                  per_video=step.per_video if step else True, counts=by_node.get(n["id"], {}),
                                  attempts=attempts, seconds=round(seconds, 2)))  # fmt: skip
    layout = (
        pipeline.layout
        if all(n["id"] in (pipeline.layout or {}) for n in version.graph["nodes"])
        else auto_layout(version.graph)
    )
    return RunDetail(**summary.model_dump(), graph=version.graph, layout=layout, nodes=nodes, inputs=r.inputs)


def _step_reads(db: Session, steps: list[PipelineStepRun], with_attempts: bool = False) -> list[StepRead]:
    videos = {
        v.id: v
        for v in db.scalars(select(Video).where(Video.id.in_({s.video_id for s in steps if s.video_id})))
    }
    attempts: dict[uuid.UUID, list[PipelineStepAttempt]] = {}
    if with_attempts and steps:
        for a in db.scalars(select(PipelineStepAttempt).where(PipelineStepAttempt.step_run_id.in_([s.id for s in steps]))
                            .order_by(PipelineStepAttempt.number)):  # fmt: skip
            attempts.setdefault(a.step_run_id, []).append(a)
    out = []
    for s in steps:
        v = videos.get(s.video_id) if s.video_id else None
        ran = [
            (a.finished_at - a.started_at).total_seconds()
            for a in attempts.get(s.id, [])
            if a.started_at and a.finished_at
        ]
        # The time its attempts ran (a retry's wait isn't counted), else start to finish.
        dur = (
            sum(ran)
            if ran
            else (s.finished_at - s.started_at).total_seconds()
            if s.finished_at and s.started_at
            else None
        )
        out.append(StepRead(id=s.id, run_id=s.run_id, node_id=s.node_id, step_type=s.step_type,
                            label=STEPS[s.step_type].label if s.step_type in STEPS else s.step_type,
                            video=Ref(id=v.id, name=v.original_filename) if v else None, status=s.status,
                            attempts=s.attempts, max_attempts=s.max_attempts, error=s.error, error_kind=s.error_kind,
                            error_label=engine.ERROR_LABELS.get(s.error_kind or "") if s.error_kind else None,
                            retry_at=s.retry_at, started_at=s.started_at, finished_at=s.finished_at,
                            duration_s=round(dur, 2) if dur is not None else None, result=s.result or {},
                            job_id=s.job_id,
                            attempt_list=[AttemptRead.model_validate(a) for a in attempts.get(s.id, [])]))  # fmt: skip
    return out


@router.get("/runs/{run_id}/steps", response_model=Page[StepRead])
def list_steps(
    run_id: uuid.UUID,
    db: DbSession,
    _: CurrentUser,
    node_id: str | None = None,
    video_id: uuid.UUID | None = None,
    status_: Annotated[list[StepStatus] | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[StepRead]:
    r = _run(db, run_id)
    version = db.get(PipelineVersion, r.version_id)
    assert version is not None
    order = {n["id"]: i for i, n in enumerate(version.graph["nodes"])}
    stmt = select(PipelineStepRun).where(PipelineStepRun.run_id == r.id)
    if node_id:
        stmt = stmt.where(PipelineStepRun.node_id == node_id)
    if video_id:
        stmt = stmt.where(PipelineStepRun.video_id == video_id)
    if status_:
        stmt = stmt.where(PipelineStepRun.status.in_(status_))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rank = func.array_position(literal_column("ARRAY[" + ",".join(f"'{n}'" for n in order) + "]::text[]"),
                               PipelineStepRun.node_id) if order else PipelineStepRun.node_id  # fmt: skip
    steps = list(db.scalars(stmt.outerjoin(Video, Video.id == PipelineStepRun.video_id)
                            .order_by(Video.created_at.nulls_last(), Video.id, rank, PipelineStepRun.id)
                            .limit(limit).offset(offset)))  # fmt: skip
    return Page[StepRead](
        items=_step_reads(db, steps, with_attempts=True), total=total, limit=limit, offset=offset
    )


@router.get("/step-runs/{step_id}", response_model=StepRead)
def get_step(step_id: uuid.UUID, db: DbSession, _: CurrentUser) -> StepRead:
    s = db.get(PipelineStepRun, step_id)
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Step not found")
    return _step_reads(db, [s], with_attempts=True)[0]


@router.post("/runs/{run_id}/retry", response_model=RetryResult)
def retry(run_id: uuid.UUID, body: RetryIn, db: DbSession, user: Processor) -> RetryResult:
    """Retry failed steps (the given ones, or all of the run's): a new attempt of each, and nothing else.
    Steps that already finished keep their results; the steps waiting on a retried one carry on after it."""
    _run(db, run_id)
    try:
        steps, to_send = engine.retry_steps(db, run_id, body.step_ids or None, user.id)
    except engine.StepStateError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    db.commit()
    engine.send(db, to_send)
    return RetryResult(retried=len(steps), steps=_step_reads(db, steps, with_attempts=True))


@router.post("/runs/{run_id}/cancel", response_model=RunSummary)
def cancel(run_id: uuid.UUID, db: DbSession, user: Processor) -> RunSummary:
    _run(db, run_id)
    try:
        run = engine.cancel_run(db, run_id, user.id)
    except engine.StepStateError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    db.commit()
    return _run_summaries(db, [run])[0]


def _log_query(db: Session, run: PipelineRun, *, q: str | None, levels: list[LogLevel] | None, node_id: str | None,
               step_run_id: uuid.UUID | None, video_id: uuid.UUID | None):  # type: ignore[no-untyped-def]  # fmt: skip
    attempt_jobs = (select(PipelineStepAttempt.job_id).join(PipelineStepRun, PipelineStepRun.id == PipelineStepAttempt.step_run_id)
                    .where(PipelineStepRun.run_id == run.id, PipelineStepAttempt.job_id.is_not(None)))  # fmt: skip
    stmt = (
        select(JobLog, PipelineStepAttempt.number, PipelineStepRun)
        .outerjoin(PipelineStepAttempt, PipelineStepAttempt.job_id == JobLog.job_id)
        .outerjoin(PipelineStepRun, PipelineStepRun.id == PipelineStepAttempt.step_run_id)
        .where(or_(JobLog.job_id == run.job_id, JobLog.job_id.in_(attempt_jobs)))
    )
    if levels:
        stmt = stmt.where(JobLog.level.in_(levels))
    if node_id:
        stmt = stmt.where(or_(PipelineStepRun.node_id == node_id, JobLog.data["node_id"].astext == node_id))
    if step_run_id:
        stmt = stmt.where(
            or_(PipelineStepRun.id == step_run_id, JobLog.data["step_run_id"].astext == str(step_run_id))
        )
    if video_id:
        stmt = stmt.where(
            or_(PipelineStepRun.video_id == video_id, JobLog.data["video_id"].astext == str(video_id))
        )
    if q:
        needle = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(search_text().ilike(f"%{needle}%", escape="\\"))  # the trigram index's expression
    return stmt


@router.get("/runs/{run_id}/logs", response_model=RunLogPage)
def run_logs(
    run_id: uuid.UUID,
    db: DbSession,
    _: CurrentUser,
    q: Annotated[
        str | None, Query(max_length=200, description="Words or any fragment of a message or its data")
    ] = None,
    level: Annotated[list[LogLevel] | None, Query()] = None,
    node_id: str | None = None,
    step_run_id: uuid.UUID | None = None,
    video_id: uuid.UUID | None = None,
    after_id: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> RunLogPage:
    """Every log line of the run, in order: the engine's own lines and every attempt's job log, searchable."""
    r = _run(db, run_id)
    q = (q or "").strip() or None
    base = _log_query(db, r, q=q, levels=level, node_id=node_id, step_run_id=step_run_id, video_id=video_id)
    rows = db.execute(base.where(JobLog.id > after_id).order_by(JobLog.id).limit(limit)).all()
    matched = db.scalar(select(func.count()).select_from(base.limit(MATCH_CAP).subquery())) or 0
    total = db.scalar(select(func.count()).select_from(
        _log_query(db, r, q=None, levels=None, node_id=None, step_run_id=None, video_id=None).subquery())) or 0  # fmt: skip
    videos = {
        v.id: v
        for v in db.scalars(
            select(Video).where(Video.id.in_({s.video_id for _, _, s in rows if s and s.video_id}))
        )
    }
    items = []
    for line, attempt, step in rows:
        v = videos.get(step.video_id) if step and step.video_id else None
        items.append(RunLogLine(id=line.id, ts=line.ts, level=line.level, message=line.message, data=line.data or {},
                                job_id=line.job_id,
                                source=(STEPS[step.step_type].label if step and step.step_type in STEPS else "run"),
                                node_id=step.node_id if step else (line.data or {}).get("node_id"),
                                step_run_id=step.id if step else None, attempt=attempt,
                                video=Ref(id=v.id, name=v.original_filename) if v else None))  # fmt: skip
    return RunLogPage(
        items=items, next_after_id=items[-1].id if len(items) == limit else None, matched=matched, total=total
    )


@router.get("/runs/{run_id}/logs.txt", response_class=StreamingResponse)
def run_logs_text(
    run_id: uuid.UUID, db: DbSession, _: CurrentUser, q: str | None = None
) -> StreamingResponse:
    """The run's complete log as plain text (one line per entry, data as JSON), streamed."""
    import json

    r = _run(db, run_id)
    stmt = _log_query(
        db, r, q=(q or "").strip() or None, levels=None, node_id=None, step_run_id=None, video_id=None
    )

    def lines() -> Iterator[bytes]:
        for line, attempt, step in db.execute(stmt.order_by(JobLog.id).execution_options(yield_per=2000)):
            src = (
                f"{STEPS[step.step_type].label if step.step_type in STEPS else step.step_type} #{attempt}"
                if step
                else "run"
            )
            data = json.dumps(line.data, separators=(",", ":"), default=str) if line.data else ""
            yield (
                f"{line.ts.isoformat()} {line.level.value.upper():7} [{src}] {line.message} {data}".rstrip().encode()
                + b"\n"
            )

    name = f"pipeline-run-{r.number}-{r.id}.log"
    return StreamingResponse(lines(), media_type="text/plain; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})  # fmt: skip


# --- schedules -----------------------------------------------------------------------------------------


def _schedule_reads(db: Session, rows: list[PipelineSchedule]) -> list[ScheduleRead]:
    pipes = {
        p.id: p for p in db.scalars(select(Pipeline).where(Pipeline.id.in_({s.pipeline_id for s in rows})))
    }
    counts = dict(db.execute(select(PipelineRun.schedule_id, func.count()).where(PipelineRun.schedule_id.in_([s.id for s in rows]))
                             .group_by(PipelineRun.schedule_id)).tuples().all()) if rows else {}  # fmt: skip
    last = {r.schedule_id: r for r in db.scalars(
        select(PipelineRun).where(PipelineRun.schedule_id.in_([s.id for s in rows])).distinct(PipelineRun.schedule_id)
        .order_by(PipelineRun.schedule_id, PipelineRun.created_at.desc()))} if rows else {}  # fmt: skip
    now = datetime.now(UTC)
    out = []
    for s in rows:
        try:
            upcoming = cron.upcoming(s.cron, s.timezone, now, 3) if s.enabled else []
        except cron.CronError:
            upcoming = []
        out.append(ScheduleRead(id=s.id, pipeline=Ref(id=s.pipeline_id, name=pipes[s.pipeline_id].name), name=s.name,
                                cron=s.cron, timezone=s.timezone, enabled=s.enabled, inputs=s.inputs or {},
                                inputs_label=inputs.describe(s.inputs or {}), only_new=s.only_new,
                                next_run_at=s.next_run_at, upcoming=upcoming, last_run_at=s.last_run_at,
                                last_outcome=s.last_outcome, run_count=counts.get(s.id, 0), last_run=_brief(last.get(s.id)),
                                created_at=s.created_at))  # fmt: skip
    return out


def _schedule(db: Session, schedule_id: uuid.UUID) -> PipelineSchedule:
    s = db.get(PipelineSchedule, schedule_id)
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Schedule not found")
    return s


def _check_cron(expr: str, tz: str) -> datetime:
    try:
        return cron.next_after(cron.parse(expr), datetime.now(UTC), tz)
    except cron.CronError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


def _check_inputs(sel: inputs.RunInputs) -> None:
    if sel.empty():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "Choose videos, sessions, or datasets to run on (or all videos)")  # fmt: skip


@router.get("/schedules", response_model=list[ScheduleRead])
def list_schedules(db: DbSession, _: CurrentUser, pipeline_id: uuid.UUID | None = None) -> list[ScheduleRead]:
    stmt = select(PipelineSchedule)
    if pipeline_id:
        stmt = stmt.where(PipelineSchedule.pipeline_id == pipeline_id)
    return _schedule_reads(db, list(db.scalars(stmt.order_by(PipelineSchedule.created_at.desc()).limit(500))))


@router.post("/schedules", response_model=ScheduleRead, status_code=status.HTTP_201_CREATED)
def create_schedule(body: ScheduleCreate, db: DbSession, user: Processor) -> ScheduleRead:
    _pipeline(db, body.pipeline_id)
    _check_inputs(body.inputs)
    nxt = _check_cron(body.cron, body.timezone)
    s = PipelineSchedule(pipeline_id=body.pipeline_id, name=body.name, cron=body.cron, timezone=body.timezone,
                         enabled=body.enabled, inputs=body.inputs.model_dump(mode="json"), only_new=body.only_new,
                         next_run_at=nxt if body.enabled else None, created_by=user.id)  # fmt: skip
    db.add(s)
    db.commit()
    return _schedule_reads(db, [s])[0]


@router.patch("/schedules/{schedule_id}", response_model=ScheduleRead)
def update_schedule(
    schedule_id: uuid.UUID, body: ScheduleUpdate, db: DbSession, _: Processor
) -> ScheduleRead:
    s = _schedule(db, schedule_id)
    fields = body.model_dump(exclude_unset=True)
    if "inputs" in fields:
        assert body.inputs is not None
        _check_inputs(body.inputs)
        s.inputs = body.inputs.model_dump(mode="json")
    for key in ("name", "cron", "timezone", "enabled", "only_new"):
        if key in fields and fields[key] is not None:
            setattr(s, key, fields[key])
    s.next_run_at = _check_cron(s.cron, s.timezone) if s.enabled else None
    db.commit()
    return _schedule_reads(db, [s])[0]


@router.delete("/schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_schedule(schedule_id: uuid.UUID, db: DbSession, _: Processor) -> None:
    db.delete(_schedule(db, schedule_id))
    db.commit()


@router.post("/schedules/{schedule_id}/run", response_model=ScheduleRead)
def run_schedule_now(schedule_id: uuid.UUID, db: DbSession, user: Processor) -> ScheduleRead:
    """Fire the schedule once now (its regular times are unchanged)."""
    s = _schedule(db, schedule_id)
    _, to_send, _ = schedules.fire(db, s, datetime.now(UTC), user_id=user.id, manual=True)
    db.commit()
    engine.send(db, to_send)
    return _schedule_reads(db, [s])[0]


# --- pipelines -----------------------------------------------------------------------------------------


@router.get("", response_model=Page[PipelineSummary])
def list_pipelines(
    db: DbSession,
    _: CurrentUser,
    templates_only: Annotated[bool | None, Query(alias="templates")] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[PipelineSummary]:
    stmt = select(Pipeline).where(Pipeline.archived_at.is_(None))
    if templates_only is not None:
        stmt = stmt.where(Pipeline.is_template.is_(templates_only))
    if q:
        stmt = stmt.where(Pipeline.name.ilike(f"%{q}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(
        db.scalars(stmt.order_by(Pipeline.updated_at.desc(), Pipeline.id).limit(limit).offset(offset))
    )
    return Page[PipelineSummary](items=_summaries(db, rows), total=total, limit=limit, offset=offset)


@router.post("", response_model=PipelineDetail, status_code=status.HTTP_201_CREATED)
def create_pipeline(body: PipelineCreate, db: DbSession, user: Processor) -> PipelineDetail:
    """A new pipeline and its version 1: from a graph, a built-in template, or another pipeline."""
    parent_version: uuid.UUID | None = None
    layout = body.layout
    if body.graph is not None:
        graph = _checked(body.graph)
    elif body.from_template:
        t = templates.get(body.from_template)
        if t is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No template {body.from_template!r}")
        graph, layout = t["graph"], layout or t["layout"]
    elif body.from_pipeline_id:
        src = _pipeline(db, body.from_pipeline_id)
        v = _latest(db, src.id)
        graph, layout, parent_version = _checked(v.graph), layout or src.layout, v.id
    else:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Give a graph, a template, or a pipeline to copy"
        )
    p = Pipeline(name=body.name, description=body.description, is_template=body.is_template,
                 run_on_upload=body.run_on_upload,
                 layout=layout or auto_layout(graph), created_by=user.id)  # fmt: skip
    db.add(p)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"A pipeline named {body.name!r} already exists"
        ) from exc
    note = body.note or (f"From the template “{body.from_template}”" if body.from_template else None)
    db.add(PipelineVersion(pipeline_id=p.id, number=1, graph=graph, graph_hash=graph_hash(graph),
                           parent_version_id=parent_version, note=note, created_by=user.id))  # fmt: skip
    db.commit()
    return _detail(db, p)


@router.get("/{pipeline_id}", response_model=PipelineDetail)
def get_pipeline(pipeline_id: uuid.UUID, db: DbSession, _: CurrentUser) -> PipelineDetail:
    return _detail(db, _pipeline(db, pipeline_id))


@router.put("/{pipeline_id}", response_model=PipelineDetail)
def update_pipeline(
    pipeline_id: uuid.UUID, body: PipelineUpdate, db: DbSession, user: Processor
) -> PipelineDetail:
    """Rename, re-describe, move nodes, or change the graph. A changed graph is saved as the next version (the
    previous one stays as it was); moving nodes only changes the layout."""
    p = db.get(Pipeline, pipeline_id, with_for_update=True)
    if p is None or p.archived_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pipeline not found")
    fields = body.model_dump(exclude_unset=True)
    for key in ("name", "description", "is_template", "run_on_upload"):
        if key in fields and fields[key] is not None:
            setattr(p, key, fields[key])
    if body.layout is not None:
        p.layout = body.layout
    if body.graph is not None:
        graph = _checked(body.graph)
        latest = _latest(db, p.id)
        h = graph_hash(graph)
        if h != latest.graph_hash:
            db.add(PipelineVersion(pipeline_id=p.id, number=latest.number + 1, graph=graph, graph_hash=h,
                                   parent_version_id=latest.id, note=body.note, created_by=user.id))  # fmt: skip
    p.updated_at = datetime.now(UTC)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"A pipeline named {body.name!r} already exists"
        ) from exc
    return _detail(db, p)


@router.delete("/{pipeline_id}", status_code=status.HTTP_204_NO_CONTENT)
def archive_pipeline(pipeline_id: uuid.UUID, db: DbSession, _: Processor) -> None:
    """Archive: hidden from lists and its schedules stop; its versions and runs stay (principle 1)."""
    p = _pipeline(db, pipeline_id)
    p.archived_at = datetime.now(UTC)
    p.name = f"{p.name} (archived {p.id.hex[:8]})"[:200]
    for s in db.scalars(select(PipelineSchedule).where(PipelineSchedule.pipeline_id == p.id)):
        s.enabled, s.next_run_at = False, None
    db.commit()


@router.get("/{pipeline_id}/versions/{number}", response_model=VersionRead)
def get_version(pipeline_id: uuid.UUID, number: int, db: DbSession, _: CurrentUser) -> VersionRead:
    v = db.scalar(
        select(PipelineVersion).where(
            PipelineVersion.pipeline_id == pipeline_id, PipelineVersion.number == number
        )
    )
    if v is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Version not found")
    return _version_read(v, _users(db, {v.created_by}))


@router.post("/{pipeline_id}/runs", response_model=RunSummary, status_code=status.HTTP_202_ACCEPTED)
def start_run(pipeline_id: uuid.UUID, body: RunCreate, db: DbSession, user: Processor) -> RunSummary:
    """Run a version (the latest by default) on the videos the inputs select, pinned now."""
    p = _pipeline(db, pipeline_id)
    if body.version is None:
        version = _latest(db, p.id)
    else:
        found = db.scalar(select(PipelineVersion).where(PipelineVersion.pipeline_id == p.id,
                                                        PipelineVersion.number == body.version))  # fmt: skip
        if found is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"{p.name} has no version {body.version}")
        version = found
    try:
        videos = inputs.resolve(db, body.inputs)
    except inputs.InputError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    if not videos:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "No ingested videos match (videos still being ingested are left out)")  # fmt: skip
    run, to_send = engine.start_run(db, version, videos, body.inputs.model_dump(mode="json"), trigger=RunTrigger.manual,
                                    user_id=user.id)  # fmt: skip
    engine.send(db, to_send)
    return _run_summaries(db, [run])[0]


# --- per video: quality checks and annotated videos ----------------------------------------------------


def _video(db: Session, video_id: uuid.UUID) -> Video:
    v = db.get(Video, video_id)
    if v is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Video not found")
    return v


@videos_router.get("/videos/{video_id}/quality", response_model=VideoQuality)
def video_quality(video_id: uuid.UUID, db: DbSession, _: CurrentUser) -> VideoQuality:
    """The video's quality flags and the latest result of each quality check."""
    v = _video(db, video_id)
    latest = db.scalars(select(VideoQualityCheck).where(VideoQualityCheck.video_id == v.id)
                        .distinct(VideoQualityCheck.check)
                        .order_by(VideoQualityCheck.check, VideoQualityCheck.created_at.desc())).all()  # fmt: skip
    return VideoQuality(
        flags=list(v.quality_flags or []), checks=[QualityCheckRead.model_validate(c) for c in latest]
    )


@videos_router.get("/videos/{video_id}/annotated", response_model=list[AnnotatedVideoRead])
def list_annotated(video_id: uuid.UUID, db: DbSession, _: CurrentUser) -> list[AnnotatedVideo]:
    _video(db, video_id)
    return list(db.scalars(select(AnnotatedVideo).where(AnnotatedVideo.video_id == video_id)
                           .order_by(AnnotatedVideo.created_at.desc()).limit(50)))  # fmt: skip


@videos_router.post(
    "/videos/{video_id}/annotated", response_model=AnnotatedVideoRead, status_code=status.HTTP_202_ACCEPTED
)
def render_annotated(
    video_id: uuid.UUID, body: AnnotatedVideoCreate, db: DbSession, user: Processor
) -> AnnotatedVideo:
    """Render the video with its latest hand, object, and movement runs drawn on (a worker job)."""
    from egolabs.cv.runs import latest_succeeded

    v = _video(db, video_id)
    runs = {k: latest_succeeded(db, v.id, k.value) for k in (CvRunKind.hand_tracking, CvRunKind.object_detection,
                                                             CvRunKind.movement)}  # fmt: skip
    if not any(runs.values()):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Nothing to draw yet: run hand tracking on this video first"
        )
    av = AnnotatedVideo(video_id=v.id, status=BuildStatus.building, created_by=user.id, options=body.model_dump(),
                        inputs={"hand_run_id": str(runs[CvRunKind.hand_tracking].id) if runs[CvRunKind.hand_tracking] else None,
                                "object_run_id": str(runs[CvRunKind.object_detection].id) if runs[CvRunKind.object_detection] else None,
                                "movement_run_id": str(runs[CvRunKind.movement].id) if runs[CvRunKind.movement] else None})  # fmt: skip
    db.add(av)
    db.commit()
    job = enqueue_job(db, "video.render_annotated", {"annotated_video_id": str(av.id)}, created_by=user.id)
    av.job_id = job.id
    db.commit()
    return av


@videos_router.get("/annotated-videos/{annotated_id}/download", response_model=Download)
def download_annotated(
    annotated_id: uuid.UUID,
    db: DbSession,
    _: CurrentUser,
    inline: Annotated[bool, Query(description="A link to play in the page rather than save")] = False,
) -> Download:
    av = db.get(AnnotatedVideo, annotated_id)
    if av is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Annotated video not found")
    if av.status != BuildStatus.ready or not av.storage_key:
        raise HTTPException(status.HTTP_409_CONFLICT, f"The annotated video is {av.status.value}")
    video = db.get(Video, av.video_id)
    stem = (video.original_filename.rsplit(".", 1)[0] if video else "video")[:120]
    name = f"{stem}-annotated.{av.storage_key.rsplit('.', 1)[-1]}"
    expires = 900
    url = storage.presign_get(
        get_settings().s3_bucket_derived, av.storage_key, expires, filename=None if inline else name
    )
    return Download(url=url, filename=name, expires_s=expires)
