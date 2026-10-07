"""
Lineage of an exported sample (spec Phase 6, principle 1: every piece of data is traceable to a raw file and
frame).

sample → dataset version → dataset
sample → annotation (at the sample's revision) → the prediction it corrects, if any
sample → movement event → the prediction it corrects, if any
event → classification run → classifier version, job;   → hand-tracking run → hand model, job
                                                        → object-detection run → object model, job
runs → video → upload → raw file (bucket, key, sha256)
sample → frames (its frame range, timestamps, evidence frames) → video

Everything is read from rows that already exist (foreign keys and `lineage_edges`), nothing is inferred.
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from egolabs.config import get_settings
from egolabs.cv.movement import evidence as evidence_codec
from egolabs.models import (
    Annotation,
    CaptureSession,
    CvRun,
    Dataset,
    DatasetVersion,
    DatasetVersionSample,
    Job,
    LineageEdge,
    ModelVersion,
    MovementEvent,
    Upload,
    Video,
)

KIND_LABEL = {
    "hand_tracking": "Hand tracking",
    "object_detection": "Object detection",
    "movement": "Movement classification",
}


class Graph:
    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: list[dict[str, str]] = []

    def node(self, id_: str, type_: str, label: str, href: str | None = None, **detail: Any) -> str:
        if id_ not in self.nodes:
            self.nodes[id_] = {"id": id_, "type": type_, "label": label, "href": href, "detail": detail}
        return id_

    def edge(self, source: str, target: str, relation: str) -> None:
        e = {"source": source, "target": target, "relation": relation}
        if e not in self.edges:
            self.edges.append(e)


def _job(db: Session, g: Graph, job_id: uuid.UUID | None, child: str, relation: str = "produced_by") -> None:
    if not job_id:
        return
    job = db.get(Job, job_id)
    if job is None:
        return
    jid = g.node(f"job:{job.id}", "job", job.type, None, status=job.status.value,
                 finished_at=job.finished_at.isoformat() if job.finished_at else None)  # fmt: skip
    g.edge(child, jid, relation)


def _model(db: Session, g: Graph, mv_id: uuid.UUID | None, child: str) -> None:
    if not mv_id:
        return
    mv = db.get(ModelVersion, mv_id)
    if mv is None:
        return
    mid = g.node(f"model_version:{mv.id}", "model_version", f"{mv.name} {mv.version}", None, kind=mv.kind,
                 adapter=mv.adapter, config=mv.config)  # fmt: skip
    g.edge(child, mid, "model")


def _run(db: Session, g: Graph, run_id: uuid.UUID | None, child: str, relation: str) -> str | None:
    if not run_id:
        return None
    run = db.get(CvRun, run_id)
    if run is None:
        return None
    base = {
        "hand_tracking": "/cv/hands",
        "object_detection": "/cv/objects",
        "movement": "/cv/movements/runs",
    }[run.kind]
    rid = g.node(f"cv_run:{run.id}", "cv_run", f"{KIND_LABEL.get(run.kind, run.kind)} run", f"{base}/{run.id}",
                 kind=run.kind, adapter=run.adapter, status=run.status.value,
                 finished_at=run.finished_at.isoformat() if run.finished_at else None)  # fmt: skip
    g.edge(child, rid, relation)
    _model(db, g, run.model_version_id, rid)
    _job(db, g, run.job_id, rid)
    _video(db, g, run.video_id, rid, "input")
    return rid


def _video(db: Session, g: Graph, video_id: uuid.UUID, child: str, relation: str) -> str | None:
    video = db.get(Video, video_id)
    if video is None:
        return None
    vid = f"video:{video.id}"
    fresh = vid not in g.nodes
    g.node(vid, "video", video.original_filename, f"/data/videos/{video.id}", duration_s=video.duration_s,
           frames=video.frame_count, fps=video.fps, width=video.width, height=video.height,
           quality_flags=list(video.quality_flags or []))  # fmt: skip
    g.edge(child, vid, relation)
    if not fresh:
        return vid
    raw = g.node(f"raw_file:{video.sha256}", "raw_file", video.storage_key.rsplit("/", 1)[-1], None,
                 bucket=get_settings().s3_bucket_raw, storage_key=video.storage_key, sha256=video.sha256,
                 size_bytes=video.size_bytes, source_kind=video.source_kind.value, source_path=video.source_path)  # fmt: skip
    g.edge(vid, raw, "stored_as")
    if video.session_id:
        sess = db.get(CaptureSession, video.session_id)
        if sess is not None:
            g.edge(vid, g.node(f"session:{sess.id}", "session", sess.name, f"/data/sessions/{sess.id}",
                               environment=sess.environment, task=sess.task), "in_session")  # fmt: skip
    edges = db.scalars(select(LineageEdge).where(LineageEdge.child_type == "video", LineageEdge.child_id == video.id,
                                                 LineageEdge.parent_type == "upload")).all()  # fmt: skip
    upload_ids = {e.parent_id: e for e in edges}
    if video.upload_id and video.upload_id not in upload_ids:
        upload_ids[video.upload_id] = None  # type: ignore[assignment]
    for up_id, e in upload_ids.items():
        up = db.get(Upload, up_id)
        if up is None:
            continue
        uid = g.node(f"upload:{up.id}", "upload", up.filename, None, size_bytes=up.size_bytes, status=up.status.value,
                     created_at=up.created_at.isoformat())  # fmt: skip
        g.edge(vid, uid, e.relation if e else "ingested_from")
        g.edge(uid, raw, "uploaded_file")
        if e is not None:
            _job(db, g, e.job_id, uid, "ingested_by")
    return vid


def sample_graph(db: Session, sample: DatasetVersionSample) -> dict[str, Any]:
    g = Graph()
    sid = g.node(f"sample:{sample.id}", "sample", f"Sample #{sample.sample_no} · {sample.class_name}", None,
                 split=sample.split, start_frame=sample.start_frame, end_frame=sample.end_frame, status=sample.status,
                 source=sample.source, confidence=sample.confidence)  # fmt: skip
    version = db.get(DatasetVersion, sample.version_id)
    if version is not None:
        dataset = db.get(Dataset, version.dataset_id)
        vid = g.node(f"dataset_version:{version.id}", "dataset_version",
                     f"{dataset.name if dataset else 'Dataset'} v{version.number}", f"/datasets/versions/{version.id}",
                     content_hash=version.content_hash, as_of=version.inputs.get("as_of"))  # fmt: skip
        g.edge(sid, vid, "member_of")
        if dataset is not None:
            g.edge(
                vid,
                g.node(f"dataset:{dataset.id}", "dataset", dataset.name, "/datasets/versions"),
                "version_of",
            )
        _job(db, g, version.job_id, vid, "built_by")

    # The annotation (at the sample's revision) and, for a correction, the prediction it corrects.
    ann = db.get(Annotation, sample.annotation_id)
    if ann is not None:
        aid = g.node(f"annotation:{ann.id}", "annotation", ann.label, f"/annotation/inspector/{ann.video_id}?frame={sample.start_frame}",
                     source=ann.source.value, revision=sample.annotation_revision, confidence=ann.confidence)  # fmt: skip
        g.edge(sid, aid, "labelled_by")
        cur = ann
        while cur.parent_annotation_id:
            parent = db.get(Annotation, cur.parent_annotation_id)
            if parent is None:
                break
            pid = g.node(f"annotation:{parent.id}", "annotation", parent.label, None, source=parent.source.value,
                         confidence=parent.confidence)  # fmt: skip
            g.edge(f"annotation:{cur.id}", pid, "corrects")
            cur = parent

    event = db.get(MovementEvent, sample.event_id)
    if event is not None:
        eid = g.node(f"event:{event.id}", "event", f"Movement event · {sample.class_name}", f"/cv/movements/events/{event.id}",
                     source=event.source.value, status=event.status.value)  # fmt: skip
        g.edge(sid, eid, "from_event")
        chain = [event]
        while chain[-1].parent_event_id:
            parent_ev = db.get(MovementEvent, chain[-1].parent_event_id)
            if parent_ev is None:
                break
            pid = g.node(f"event:{parent_ev.id}", "event", "Predicted event", f"/cv/movements/events/{parent_ev.id}",
                         source=parent_ev.source.value, status=parent_ev.status.value, confidence=parent_ev.confidence)  # fmt: skip
            g.edge(f"event:{chain[-1].id}", pid, "corrects")
            chain.append(parent_ev)
        prediction = chain[-1]
        pnode = f"event:{prediction.id}"
        _run(db, g, event.run_id, pnode, "classified_by")
        _run(db, g, event.hand_run_id, pnode, "keypoints_from")
        _run(db, g, event.object_run_id, pnode, "objects_from")
        ev = prediction.evidence or {}
        frames = evidence_codec.decode(ev.get("frames", []))
        fid = g.node(f"frames:{sample.video_id}:{sample.start_frame}-{sample.end_frame}", "frames",
                     f"Frames {sample.start_frame}–{sample.end_frame}",
                     f"/annotation/inspector/{sample.video_id}?frame={sample.start_frame}",
                     start_frame=sample.start_frame, end_frame=sample.end_frame, start_s=sample.start_s,
                     end_s=sample.end_s, evidence_frames=len(frames),
                     evidence_first=frames[0] if frames else None, evidence_last=frames[-1] if frames else None)  # fmt: skip
        g.edge(sid, fid, "spans")
        vnode = _video(db, g, sample.video_id, fid, "frames_of")
        if vnode:
            g.edge(fid, f"raw_file:{db.get(Video, sample.video_id).sha256}", "decoded_from")  # type: ignore[union-attr]
    # Reachable along the edges from the sample, not merely present.
    seen, todo = {sid}, [sid]
    while todo:
        cur_id = todo.pop()
        for e in g.edges:
            if e["source"] == cur_id and e["target"] not in seen:
                seen.add(e["target"])
                todo.append(e["target"])
    reaches = any(g.nodes[n]["type"] == "raw_file" for n in seen if n in g.nodes)
    return {"root": sid, "nodes": list(g.nodes.values()), "edges": g.edges, "reaches_raw_file": reaches}
