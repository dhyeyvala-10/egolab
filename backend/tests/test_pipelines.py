"""
Pipelines (spec Phase 7): graphs and versions, runs, retries, logs, schedules, and quality checks, on real
clips made with ffmpeg and run by the real step code (a failure is caused for real: the raw file is taken out
of storage, or storage is unreachable).

Acceptance: a failed step can be retried without rerunning completed steps; every run has complete,
searchable logs.
"""

import subprocess
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from botocore.exceptions import EndpointConnectionError
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError

from egolabs import storage
from egolabs.config import get_settings
from egolabs.models import (
    Job,
    JobLog,
    JobStatus,
    PipelineStepAttempt,
    PipelineStepRun,
    StepStatus,
    Upload,
    Video,
    VideoQualityCheck,
)
from egolabs.pipelines import cron, engine
from egolabs.pipelines.graph import GraphError, graph_hash, validate
from tests.conftest import auth_header, drain
from tests.media import upload_file

P = "/api/v1/pipelines"


@pytest.fixture
def h(admin):
    return auth_header(admin)


def clip(path: Path, src: str = "testsrc2", vf: str | None = None, size: str = "320x240", seconds: float = 3,
         crf: int = 23) -> Path:  # fmt: skip
    args = [
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"{src}=size={size}:rate=30",
        "-t",
        str(seconds),
    ]
    if vf:
        args += ["-vf", vf]
    subprocess.run([*args, "-c:v", "libx264", "-crf", str(crf), "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def ingest(client, h, enqueued, db, path: Path, session_id: str | None = None) -> str:
    up = upload_file(client, h, path, session_id=session_id)
    drain(enqueued)
    db.expire_all()
    return str(db.get(Upload, uuid.UUID(up["id"])).video_id)


def node(nid: str, type_: str, config: dict | None = None, retries: int = 0) -> dict:
    return {"id": nid, "type": type_, "config": config or {}, "retries": retries}


def edges(*pairs: str) -> list[dict]:
    return [{"from": p.split(">")[0], "to": p.split(">")[1]} for p in pairs]


CHECKS = {
    "nodes": [node("ingest", "ingest"), node("frames", "extract_frames"), node("blur", "quality_blur"),
              node("light", "quality_low_light")],
    "edges": edges("ingest>frames", "frames>blur", "frames>light"),
}  # fmt: skip


def create(client, h, graph: dict, name: str = "Checks") -> dict:
    res = client.post(P, json={"name": name, "graph": graph}, headers=h)
    assert res.status_code == 201, res.text
    return res.json()


def start(client, h, pipeline_id: str, **inputs) -> dict:
    res = client.post(f"{P}/{pipeline_id}/runs", json={"inputs": inputs}, headers=h)
    assert res.status_code == 202, res.text
    return res.json()


def steps(client, h, run_id: str) -> list[dict]:
    return client.get(f"{P}/runs/{run_id}/steps", params={"limit": 500}, headers=h).json()["items"]


def by(items: list[dict], video: str, nid: str) -> dict:
    return next(s for s in items if s["node_id"] == nid and (s["video"] or {}).get("id") == video)


# --- graph and cron --------------------------------------------------------------------------------------


def test_graph_validation_reports_every_problem_and_normalizes():
    g = validate({"nodes": [node("hands", "hand_tracking"), node("fingers", "finger_tracking")],
                  "edges": edges("hands>fingers")})  # fmt: skip
    assert [n["id"] for n in g["nodes"]] == ["hands", "fingers"]
    assert g["nodes"][0]["config"] == {"adapter": None, "adapter_config": {}, "stride": 1, "reuse": False}
    reordered = {"nodes": list(reversed(g["nodes"])), "edges": g["edges"]}
    assert graph_hash(g) == graph_hash(reordered)

    cases = [
        ({"nodes": [node("fingers", "finger_tracking")], "edges": []}, "Finger tracking needs Hand tracking before it"),
        ({"nodes": [node("a", "ingest"), node("b", "extract_frames")], "edges": edges("a>b", "b>a")}, "loop"),
        ({"nodes": [node("a", "ingest"), node("b", "ingest")], "edges": []}, "appears twice"),
        ({"nodes": [node("x", "teleport")], "edges": []}, "Unknown step type"),
        ({"nodes": [node("d", "dataset_build", {"dataset": "D"}), node("r", "render_video")], "edges": edges("d>r")},
         "can't come after"),
        ({"nodes": [node("b", "quality_blur", {"max_fraction": 2})], "edges": []}, "max_fraction"),
        ({"nodes": [node("d", "dataset_build", {"dataset": "D", "split": {"train": 0.9, "val": 0.2, "test": 0}})],
          "edges": []}, "add up to 1"),
        ({"nodes": [node("h", "hand_tracking", {"adapter": "rtmpose-hands"})], "edges": []}, "stub"),
        ({"nodes": [node("a", "ingest", retries=9)], "edges": []}, "retries"),
        ({"nodes": [node("Bad Id", "ingest")], "edges": []}, "Step id"),
        ({"nodes": [], "edges": []}, "at least one step"),
    ]  # fmt: skip
    for graph, needle in cases:
        with pytest.raises(GraphError) as exc:
            validate(graph)
        assert needle in str(exc.value), (needle, exc.value.errors)


def test_cron_parsing_and_time_zones():
    after = datetime(2026, 9, 24, 23, 0, tzinfo=UTC)
    assert cron.upcoming("*/20 * * * *", "UTC", after, 3) == [
        after + timedelta(minutes=m) for m in (20, 40, 60)
    ]
    # Weekdays at 02:30 in Kolkata (UTC+5:30): Friday 25th has passed by 23:00 UTC on the 24th, so Monday.
    assert cron.upcoming("30 2 * * mon-fri", "Asia/Kolkata", after, 1) == [
        datetime(2026, 9, 27, 21, 0, tzinfo=UTC)
    ]
    # 02:30 doesn't exist in New York on 8 March 2026 (clocks go forward): skipped, not fired twice.
    ny = cron.upcoming("30 2 * * *", "America/New_York", datetime(2026, 3, 7, 0, 0, tzinfo=UTC), 3)
    assert [t.day for t in ny] == [7, 9, 10]
    # Both day fields restricted: either matches (the 1st of the month or a Sunday).
    days = cron.upcoming("0 0 1 * sun", "UTC", datetime(2026, 9, 30, tzinfo=UTC), 3)
    assert [(t.month, t.day) for t in days] == [(10, 1), (10, 4), (10, 11)]
    assert cron.upcoming("@daily", "UTC", after, 1) == [datetime(2026, 9, 25, tzinfo=UTC)]
    for bad in ("* * *", "61 * * * *", "* * * * mo", "5-1 * * * *", "*/0 * * * *"):
        with pytest.raises(cron.CronError):
            cron.parse(bad)
    with pytest.raises(cron.CronError):
        cron.upcoming("0 0 * * *", "Mars/Olympus", after)


# --- versions and templates ------------------------------------------------------------------------------


def test_versions_templates_and_immutability(client, db, h, viewer):
    templates = client.get(f"{P}/templates", headers=h).json()
    assert {t["key"] for t in templates} >= {"process-videos", "end-to-end", "quality-audit", "reclassify"}
    catalog = {s["key"]: s for s in client.get(f"{P}/steps", headers=h).json()}
    assert len(catalog) == 13 and catalog["export"]["requires"] == ["dataset_build"]
    assert (
        catalog["dataset_build"]["per_video"] is False
        and "properties" in catalog["quality_blur"]["config_schema"]
    )

    p = client.post(P, json={"name": "Full", "from_template": "process-videos"}, headers=h).json()
    assert (
        p["latest_version"] == 1
        and p["step_count"] == 11
        and set(p["layout"]) == {n["id"] for n in p["version"]["graph"]["nodes"]}
    )
    graph = p["version"]["graph"]
    # Moving nodes doesn't make a version; changing a setting does.
    moved = client.put(f"{P}/{p['id']}", json={"layout": {**p["layout"], "ingest": {"x": 5, "y": 5}}, "graph": graph},
                       headers=h).json()  # fmt: skip
    assert moved["latest_version"] == 1 and moved["layout"]["ingest"] == {"x": 5, "y": 5}
    next(n for n in graph["nodes"] if n["id"] == "hands")["config"]["stride"] = 2
    v2 = client.put(f"{P}/{p['id']}", json={"graph": graph, "note": "every other frame"}, headers=h).json()
    assert v2["latest_version"] == 2 and v2["version"]["parent_version_id"] == p["version"]["id"]
    v1 = client.get(f"{P}/{p['id']}/versions/1", headers=h).json()["graph"]
    assert next(n for n in v1["nodes"] if n["id"] == "hands")["config"]["stride"] == 1
    bad = client.put(
        f"{P}/{p['id']}", json={"graph": {"nodes": [node("f", "finger_tracking")], "edges": []}}, headers=h
    )
    assert bad.status_code == 422 and bad.json()["detail"]["errors"][0]["node_id"] == "f"
    check = client.post(
        f"{P}/validate", json={"nodes": [node("f", "finger_tracking")], "edges": []}, headers=h
    ).json()
    assert check["ok"] is False and "Hand tracking" in check["errors"][0]["message"]

    with pytest.raises(DBAPIError, match="immutable"):
        db.execute(text("UPDATE pipeline_versions SET note = 'x'"))
    db.rollback()

    copy = client.post(
        P, json={"name": "Copy", "from_pipeline_id": p["id"], "is_template": True}, headers=h
    ).json()
    assert copy["version"]["parent_version_id"] == v2["version"]["id"] and copy["is_template"] is True
    assert [x["name"] for x in client.get(P, params={"templates": True}, headers=h).json()["items"]] == [
        "Copy"
    ]
    assert client.post(P, json={"name": "Full", "from_template": "reclassify"}, headers=h).status_code == 409
    assert client.post(P, json={"name": "N", "from_template": "nope"}, headers=h).status_code == 404
    vh = auth_header(viewer)
    assert client.post(P, json={"name": "V", "from_template": "reclassify"}, headers=vh).status_code == 403
    assert client.get(P, headers=vh).status_code == 200
    assert client.delete(f"{P}/{p['id']}", headers=h).status_code == 204
    assert client.get(f"{P}/{p['id']}", headers=h).status_code == 404


# --- acceptance ------------------------------------------------------------------------------------------


def test_a_failed_step_is_retried_without_rerunning_completed_steps(client, db, h, enqueued, tmp_path):
    a = ingest(client, h, enqueued, db, clip(tmp_path / "a.mp4"))
    b = ingest(client, h, enqueued, db, clip(tmp_path / "b.mp4", src="mandelbrot"))
    raw = get_settings().s3_bucket_raw
    key_b = db.get(Video, uuid.UUID(b)).storage_key
    saved = storage.get_bytes(raw, key_b)
    storage.delete(raw, key_b)  # B's raw file goes missing: its ingest check fails for real

    p = create(client, h, CHECKS)
    run = start(client, h, p["id"], video_ids=[a, b])
    drain(enqueued)
    first = steps(client, h, run["id"])
    assert all(by(first, a, n)["status"] == "succeeded" for n in ("ingest", "frames", "blur", "light"))
    failed = by(first, b, "ingest")
    assert (
        failed["status"] == "failed"
        and failed["error_kind"] == "missing_input"
        and "missing from storage" in failed["error"]
    )
    assert all(by(first, b, n)["status"] == "pending" for n in ("frames", "blur", "light"))
    detail = client.get(f"{P}/runs/{run['id']}", headers=h).json()
    assert detail["status"] == "failed" and detail["error"] == "1 step failed; 3 waiting on them"
    done_before = {
        s["id"]: (s["attempts"], s["job_id"], s["result"]) for s in first if s["status"] == "succeeded"
    }
    checks_before = db.scalar(select(func.count()).select_from(VideoQualityCheck))

    storage.put_bytes(saved, raw, key_b)  # the file is back
    res = client.post(f"{P}/runs/{run['id']}/retry", json={}, headers=h).json()
    assert res["retried"] == 1 and res["steps"][0]["id"] == failed["id"] and res["steps"][0]["attempts"] == 2
    drain(enqueued)

    after = steps(client, h, run["id"])
    assert client.get(f"{P}/runs/{run['id']}", headers=h).json()["status"] == "succeeded"
    for s in after:
        if s["id"] in done_before:  # completed steps: never run again
            assert (s["attempts"], s["job_id"], s["result"]) == done_before[s["id"]]
    ingest_b = by(after, b, "ingest")
    assert [(x["number"], x["status"], x["reason"]) for x in ingest_b["attempt_list"]] == [
        (1, "failed", "first"),
        (2, "succeeded", "manual_retry"),
    ]
    ran = sum((datetime.fromisoformat(x["finished_at"]) - datetime.fromisoformat(x["started_at"])).total_seconds()
              for x in ingest_b["attempt_list"])  # fmt: skip
    assert ingest_b["duration_s"] == round(ran, 2)  # the time its attempts ran, not the wait for the retry
    assert all(
        by(after, b, n)["attempts"] == 1 and by(after, b, n)["status"] == "succeeded"
        for n in ("frames", "blur", "light")
    )
    # Only B's two checks are new; A's weren't measured again.
    assert db.scalar(select(func.count()).select_from(VideoQualityCheck)) == checks_before + 2
    assert client.post(f"{P}/runs/{run['id']}/retry", json={}, headers=h).status_code == 409


def test_every_run_has_complete_searchable_logs(client, db, h, enqueued, tmp_path):
    a = ingest(client, h, enqueued, db, clip(tmp_path / "a.mp4"))
    b = ingest(client, h, enqueued, db, clip(tmp_path / "b.mp4", src="mandelbrot"))
    raw = get_settings().s3_bucket_raw
    key_b = db.get(Video, uuid.UUID(b)).storage_key
    saved = storage.get_bytes(raw, key_b)
    storage.delete(raw, key_b)
    p = create(client, h, CHECKS)
    run = start(client, h, p["id"], video_ids=[a, b])
    drain(enqueued)
    storage.put_bytes(saved, raw, key_b)
    client.post(f"{P}/runs/{run['id']}/retry", json={}, headers=h)
    drain(enqueued)

    # Complete: the engine's log and every attempt's job log, nothing else.
    jobs = [run["job_id"], *db.scalars(select(PipelineStepAttempt.job_id).join(PipelineStepRun)
                                        .where(PipelineStepRun.run_id == uuid.UUID(run["id"])))]  # fmt: skip
    assert len(jobs) == 1 + 8 + 1  # 8 steps, one of them tried twice
    expected = db.scalar(select(func.count()).select_from(JobLog).where(JobLog.job_id.in_(jobs)))
    lines, after = [], 0
    while True:
        page = client.get(
            f"{P}/runs/{run['id']}/logs", params={"after_id": after, "limit": 7}, headers=h
        ).json()
        lines += page["items"]
        if page["next_after_id"] is None:
            break
        after = page["next_after_id"]
    assert len(lines) == page["total"] == expected
    assert {str(line["job_id"]) for line in lines} == {str(j) for j in jobs}  # every attempt logged
    assert [line["id"] for line in lines] == sorted(line["id"] for line in lines)
    assert lines[0]["source"] == "run" and "started on 2 videos" in lines[0]["message"]

    def search(**params) -> dict:
        return client.get(f"{P}/runs/{run['id']}/logs", params={"limit": 1000, **params}, headers=h).json()

    missing = search(q="missing from storage")
    assert missing["matched"] >= 2  # the attempt's own error and the engine's "Failed …" line
    assert all("missing from storage" in (m["message"] + str(m["data"])) for m in missing["items"])
    assert {m["source"] for m in missing["items"]} >= {"run", "Ingest check"}
    errors = search(level="error")
    assert errors["items"] and all(e["level"] == "error" for e in errors["items"])
    assert any("Traceback" in str(e["data"]) for e in errors["items"])  # the failure's traceback is kept
    # Structured data is searchable too (a metric name), and filters combine.
    blur = search(q="below_threshold", node_id="blur")
    assert blur["matched"] == 2 and {m["video"]["id"] for m in blur["items"]} == {a, b}
    only_b = search(video_id=b, node_id="ingest")
    assert {m["attempt"] for m in only_b["items"] if m["attempt"]} == {1, 2}
    assert search(q="50%_literal")["matched"] == 0  # % and _ are literal, not wildcards
    txt = client.get(f"{P}/runs/{run['id']}/logs.txt", headers=h)
    assert txt.status_code == 200 and len(txt.text.strip().splitlines()) == expected
    assert "[Ingest check #1]" in txt.text and "[run]" in txt.text


# --- retries, skips, recovery ----------------------------------------------------------------------------


def test_transient_failure_retries_on_its_own(client, db, h, enqueued, tmp_path, monkeypatch):
    a = ingest(client, h, enqueued, db, clip(tmp_path / "a.mp4"))
    real = storage.object_size
    calls = {"n": 0}

    def flaky(bucket: str, key: str) -> int | None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise EndpointConnectionError(endpoint_url="http://storage:9000")
        return real(bucket, key)

    monkeypatch.setattr(storage, "object_size", flaky)
    p = create(client, h, {"nodes": [node("ingest", "ingest", retries=2), node("frames", "extract_frames")],
                           "edges": edges("ingest>frames")})  # fmt: skip
    run = start(client, h, p["id"], video_ids=[a])
    drain(enqueued)
    s = by(steps(client, h, run["id"]), a, "ingest")
    assert s["status"] == "retry_wait" and s["error_kind"] == "storage_unreachable" and s["retry_at"]
    assert client.get(f"{P}/runs/{run['id']}", headers=h).json()["status"] == "running"
    assert engine.tick(db, datetime.now(UTC))["retries"] == 0  # not due yet
    assert engine.tick(db, datetime.now(UTC) + timedelta(seconds=31))["retries"] == 1
    drain(enqueued)
    s = by(steps(client, h, run["id"]), a, "ingest")
    assert s["status"] == "succeeded" and [x["reason"] for x in s["attempt_list"]] == ["first", "auto_retry"]
    assert client.get(f"{P}/runs/{run['id']}", headers=h).json()["status"] == "succeeded"


def test_a_corrupt_video_is_skipped_with_the_steps_after_it(client, db, h, enqueued, tmp_path):
    good = ingest(client, h, enqueued, db, clip(tmp_path / "good.mp4"))
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"\x00\x00\x00\x18ftypmp42" + bytes(range(256)) * 400)
    bad = ingest(client, h, enqueued, db, broken)
    assert db.get(Video, uuid.UUID(bad)).status.value == "corrupt"
    p = create(client, h, CHECKS)
    run = start(client, h, p["id"], video_ids=[good, bad])
    drain(enqueued)
    items = steps(client, h, run["id"])
    assert by(items, bad, "ingest")["status"] == "skipped" and "corrupt" in by(items, bad, "ingest")["error"]
    assert all(by(items, bad, n)["status"] == "skipped" for n in ("frames", "blur", "light"))
    assert all(by(items, good, n)["status"] == "succeeded" for n in ("ingest", "frames", "blur", "light"))
    assert client.get(f"{P}/runs/{run['id']}", headers=h).json()["status"] == "succeeded"


def test_a_job_whose_worker_died_is_recovered(client, db, h, enqueued, tmp_path):
    a = ingest(client, h, enqueued, db, clip(tmp_path / "a.mp4"))
    p = create(client, h, {"nodes": [node("ingest", "ingest")], "edges": []})
    run = start(client, h, p["id"], video_ids=[a])
    s = steps(client, h, run["id"])[0]
    # The worker took the job and died: running, no heartbeat for ten minutes.
    stale = datetime.now(UTC) - timedelta(minutes=10)
    db.execute(update(Job).where(Job.id == uuid.UUID(s["job_id"])).values(status=JobStatus.running, started_at=stale,
                                                                          heartbeat_at=stale))  # fmt: skip
    db.execute(
        update(PipelineStepRun)
        .where(PipelineStepRun.id == uuid.UUID(s["id"]))
        .values(status=StepStatus.running)
    )
    db.commit()
    assert engine.tick(db)["orphans"] == 1
    s = steps(client, h, run["id"])[0]
    assert s["status"] == "failed" and s["error_kind"] == "worker_lost" and s["error_label"] == "Worker lost"
    assert client.get(f"/api/v1/jobs/{s['job_id']}", headers=h).json()["status"] == "failed"
    enqueued.clear()
    client.post(f"{P}/runs/{run['id']}/retry", json={}, headers=h)
    drain(enqueued)
    assert client.get(f"{P}/runs/{run['id']}", headers=h).json()["status"] == "succeeded"


def test_cancel_stops_steps_that_have_not_started(client, db, h, enqueued, tmp_path):
    a = ingest(client, h, enqueued, db, clip(tmp_path / "a.mp4"))
    p = create(client, h, CHECKS)
    run = start(client, h, p["id"], video_ids=[a])
    res = client.post(f"{P}/runs/{run['id']}/cancel", headers=h)
    assert res.status_code == 200 and res.json()["status"] == "cancelled"
    drain(enqueued)  # the queued job was cancelled: it doesn't run
    assert {s["status"] for s in steps(client, h, run["id"])} == {"cancelled"}
    assert client.post(f"{P}/runs/{run['id']}/cancel", headers=h).status_code == 409
    assert client.post(f"{P}/runs/{run['id']}/retry", json={}, headers=h).status_code == 409


def test_run_requests_are_checked(client, db, h, enqueued, viewer, tmp_path):
    a = ingest(client, h, enqueued, db, clip(tmp_path / "a.mp4"))
    p = create(client, h, CHECKS)
    assert client.post(f"{P}/{p['id']}/runs", json={"inputs": {}}, headers=h).status_code == 422
    assert (
        client.post(
            f"{P}/{p['id']}/runs", json={"inputs": {"video_ids": [str(uuid.uuid4())]}}, headers=h
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"{P}/{p['id']}/runs", json={"inputs": {"video_ids": [a]}, "version": 9}, headers=h
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"{P}/{p['id']}/runs", json={"inputs": {"video_ids": [a]}}, headers=auth_header(viewer)
        ).status_code
        == 403
    )
    assert client.get(f"{P}/runs/{uuid.uuid4()}", headers=h).status_code == 404
    assert (
        client.post(f"/api/v1/videos/{a}/annotated", json={}, headers=h).status_code == 409
    )  # nothing to draw yet
    assert client.get(f"/api/v1/videos/{a}/annotated", headers=h).json() == []


# --- schedules -------------------------------------------------------------------------------------------


def test_schedules_fire_on_time_and_take_only_new_videos(client, db, h, enqueued, tmp_path):
    sess = client.post("/api/v1/sessions", json={"task": "nightly"}, headers=h).json()["id"]
    a = ingest(client, h, enqueued, db, clip(tmp_path / "a.mp4"), session_id=sess)
    p = create(client, h, CHECKS)
    assert (
        client.post(f"{P}/schedules/preview", json={"cron": "*/10 * * * *"}, headers=h).json()["ok"] is True
    )
    bad = client.post(f"{P}/schedules/preview", json={"cron": "99 * * * *"}, headers=h).json()
    assert bad["ok"] is False and "minute" in bad["error"]
    assert client.post(f"{P}/schedules", json={"pipeline_id": p["id"], "name": "x", "cron": "nope",
                                               "inputs": {"session_ids": [sess]}}, headers=h).status_code == 422  # fmt: skip
    s = client.post(f"{P}/schedules", json={"pipeline_id": p["id"], "name": "Every 10 min", "cron": "*/10 * * * *",
                                            "timezone": "Europe/London", "inputs": {"session_ids": [sess]}},
                    headers=h).json()  # fmt: skip
    due = datetime.fromisoformat(s["next_run_at"])
    assert due > datetime.now(UTC) and due.minute % 10 == 0 and len(s["upcoming"]) == 3

    assert engine.tick(db, due - timedelta(seconds=1))["schedules_fired"] == 0
    assert engine.tick(db, due)["schedules_fired"] == 1
    drain(enqueued)
    runs = client.get(f"{P}/runs", params={"schedule_id": s["id"]}, headers=h).json()["items"]
    assert len(runs) == 1 and runs[0]["trigger"] == "schedule" and runs[0]["status"] == "succeeded"
    assert runs[0]["video_count"] == 1
    s = client.get(f"{P}/schedules", headers=h).json()[0]
    assert s["last_outcome"] == "Started run #1 on 1 video" and datetime.fromisoformat(s["next_run_at"]) > due

    b = ingest(client, h, enqueued, db, clip(tmp_path / "b.mp4", src="mandelbrot"), session_id=sess)
    engine.tick(db, datetime.fromisoformat(s["next_run_at"]))
    drain(enqueued)
    runs = client.get(f"{P}/runs", params={"schedule_id": s["id"]}, headers=h).json()["items"]
    assert len(runs) == 2 and runs[0]["video_count"] == 1
    assert client.get(f"{P}/runs/{runs[0]['id']}", headers=h).json()["inputs"]["video_ids"] == [b]
    s = client.post(f"{P}/schedules/{s['id']}/run", headers=h).json()
    assert s["last_outcome"] == "No new videos to process (run now)"
    off = client.patch(f"{P}/schedules/{s['id']}", json={"enabled": False}, headers=h).json()
    assert off["enabled"] is False and off["next_run_at"] is None
    assert client.delete(f"{P}/schedules/{s['id']}", headers=h).status_code == 204
    _ = a


def test_pipelines_marked_to_run_on_uploads_start_by_themselves(client, db, h, enqueued, tmp_path, admin):
    auto = create(client, h, CHECKS, name="On upload")
    assert auto["run_on_upload"] is False
    res = client.put(f"{P}/{auto['id']}", json={"run_on_upload": True}, headers=h)
    assert (
        res.status_code == 200 and res.json()["run_on_upload"] is True and res.json()["latest_version"] == 1
    )
    manual = create(client, h, CHECKS, name="By hand")
    archived = client.post(P, json={"name": "Gone", "graph": CHECKS, "run_on_upload": True}, headers=h).json()
    assert archived["run_on_upload"] is True
    assert client.delete(f"{P}/{archived['id']}", headers=h).status_code == 204

    video = ingest(client, h, enqueued, db, clip(tmp_path / "new.mp4"))
    runs = client.get(f"{P}/runs", params={"pipeline_id": auto["id"]}, headers=h).json()["items"]
    assert len(runs) == 1
    assert (runs[0]["trigger"], runs[0]["status"], runs[0]["video_count"]) == ("upload", "succeeded", 1)
    detail = client.get(f"{P}/runs/{runs[0]['id']}", headers=h).json()
    assert detail["inputs"]["video_ids"] == [video] and detail["created_by"]["id"] == admin["user"]["id"]
    assert {s["status"] for s in steps(client, h, runs[0]["id"])} == {"succeeded"}
    for other in (manual, archived):
        assert client.get(f"{P}/runs", params={"pipeline_id": other["id"]}, headers=h).json()["total"] == 0
    derive = db.scalar(select(Job).where(Job.type == "ingest.derivatives").order_by(Job.created_at.desc()))
    assert derive.result["pipeline_runs"] == ["On upload #1"]

    # Making the video's derivatives again doesn't start the pipeline a second time.
    from egolabs.pipelines import auto as auto_runs

    assert auto_runs.start_for_video(db, uuid.UUID(video)) == []
    # A corrupt upload isn't processed.
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video at all" * 100)
    ingest(client, h, enqueued, db, bad)
    assert client.get(f"{P}/runs", params={"pipeline_id": auto["id"]}, headers=h).json()["total"] == 1


def test_a_pipeline_that_cannot_start_never_fails_the_upload(client, db, h, enqueued, tmp_path, monkeypatch):
    from egolabs.pipelines import auto as auto_runs

    client.post(P, json={"name": "Broken", "graph": CHECKS, "run_on_upload": True}, headers=h)

    def boom(*_a, **_k):
        raise RuntimeError("engine unavailable")

    monkeypatch.setattr(auto_runs.engine, "start_run", boom)
    video = ingest(client, h, enqueued, db, clip(tmp_path / "ok.mp4"))
    assert db.get(Video, uuid.UUID(video)).status.value == "ready"
    derive = db.scalar(select(Job).where(Job.type == "ingest.derivatives").order_by(Job.created_at.desc()))
    assert derive.status == JobStatus.succeeded and derive.result["pipeline_runs"] == []
    warned = db.scalars(select(JobLog.message).where(JobLog.job_id == derive.id)).all()
    assert "Could not start the pipelines that run on new uploads" in warned


# --- quality checks --------------------------------------------------------------------------------------


def test_quality_checks_flag_blur_low_light_and_near_duplicates(client, db, h, enqueued, tmp_path):
    sharp = ingest(client, h, enqueued, db, clip(tmp_path / "sharp.mp4"))
    recoded = ingest(client, h, enqueued, db, clip(tmp_path / "recoded.mp4", vf="scale=480:360", crf=34))
    blurry = ingest(
        client, h, enqueued, db, clip(tmp_path / "blurry.mp4", src="mandelbrot", vf="boxblur=12:3")
    )
    dark = ingest(
        client, h, enqueued, db, clip(tmp_path / "dark.mp4", src="smptebars", vf="eq=brightness=-0.45")
    )
    p = create(client, h, {"nodes": CHECKS["nodes"] + [node("dupes", "quality_duplicates")],
                           "edges": CHECKS["edges"] + edges("frames>dupes")})  # fmt: skip
    run = start(client, h, p["id"], video_ids=[sharp, recoded, blurry, dark])
    drain(enqueued)
    assert client.get(f"{P}/runs/{run['id']}", headers=h).json()["status"] == "succeeded"
    db.expire_all()
    flags = {v: set(db.get(Video, uuid.UUID(v)).quality_flags) for v in (sharp, recoded, blurry, dark)}
    assert (
        "near_duplicate" in flags[sharp] and "near_duplicate" in flags[recoded]
    )  # the same footage, re-encoded
    assert "near_duplicate" not in flags[blurry] | flags[dark]
    assert "blurry" in flags[blurry] and "blurry" not in flags[sharp] | flags[recoded]
    assert "low_light" in flags[dark] and "low_light" not in flags[sharp] | flags[recoded] | flags[blurry]
    q = client.get(f"/api/v1/videos/{recoded}/quality", headers=h).json()
    checks = {c["check"]: c for c in q["checks"]}
    assert set(checks) == {"blur", "low_light", "duplicates"}
    assert checks["duplicates"]["metrics"]["matches"][0]["video_id"] == sharp
    assert checks["duplicates"]["metrics"]["matches"][0]["overlap"] >= 0.6
    assert checks["blur"]["metrics"]["sharpness"]["median"] > checks["blur"]["metrics"]["threshold"]
    facets = client.get("/api/v1/datasets/facets", headers=h).json()["quality_flags"]
    described = {f["flag"]: f for f in facets}
    assert described["blurry"]["videos"] == sum("blurry" in f for f in flags.values())
    assert described["near_duplicate"]["videos"] == 2 and described["near_duplicate"]["description"]


# --- end to end on a real clip ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def grasp(tmp_path_factory):
    from egolabs.cv import samples

    return samples.make_scene_clip(tmp_path_factory.mktemp("p7") / "grasp.mp4", samples.grasp_scene())


def test_end_to_end_template_on_a_real_clip(client, db, h, enqueued, grasp, tmp_path):
    import httpx
    import numpy as np

    from egolabs.render import SKELETON

    sess = client.post("/api/v1/sessions", json={"task": "grasp"}, headers=h).json()["id"]
    video_id = ingest(client, h, enqueued, db, grasp.path, session_id=sess)
    frames = db.get(Video, uuid.UUID(video_id)).frame_count
    p = client.post(P, json={"name": "End to end", "from_template": "end-to-end"}, headers=h).json()
    run = start(client, h, p["id"], session_ids=[sess])
    drain(enqueued)
    detail = client.get(f"{P}/runs/{run['id']}", headers=h).json()
    assert detail["status"] == "succeeded", detail
    assert all(n["counts"] == {"succeeded": 1} for n in detail["nodes"]), detail["nodes"]
    items = steps(client, h, run["id"])
    result = {s["node_id"]: s["result"] for s in items}

    assert result["hands"]["tracks"] >= 1 and not result["hands"]["reused"]
    assert result["fingers"]["finger_rows"] == 5 * result["fingers"]["hand_rows"] > 0
    events = client.get(
        "/api/v1/movement/events", params={"video_id": video_id, "limit": 200}, headers=h
    ).json()["items"]
    assert len(events) >= 5 and {e["run_id"] for e in events} == {result["movement"]["cv_run_id"]}
    assert result["occlusion"]["metrics"]["finger_observations"] == result["fingers"]["finger_rows"]

    # The annotated video: every frame, the skeleton drawn in, downloadable under a readable name.
    av = client.get(f"/api/v1/videos/{video_id}/annotated", headers=h).json()[0]
    assert (
        av["id"] == result["render"]["annotated_video_id"]
        and av["status"] == "ready"
        and av["frames"] == frames
    )
    link = client.get(f"/api/v1/annotated-videos/{av['id']}/download", headers=h).json()
    assert link["filename"] == "grasp-annotated.mp4" and "response-content-disposition" in link["url"]
    inline = client.get(
        f"/api/v1/annotated-videos/{av['id']}/download", params={"inline": True}, headers=h
    ).json()
    assert "response-content-disposition" not in inline["url"]  # to play in the page
    res = httpx.get(link["url"])
    assert res.status_code == 200 and "grasp-annotated.mp4" in res.headers["content-disposition"]
    out = tmp_path / "annotated.mp4"
    out.write_bytes(res.content)
    probe = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                            "stream=nb_read_frames,codec_name,width,height", "-of", "csv=p=0", str(out)],
                           capture_output=True, text=True, check=True).stdout.strip()  # fmt: skip
    codec, w, hgt, n = probe.split(",")
    assert codec == "h264" and int(n) == frames and (int(w), int(hgt)) == (av["width"], av["height"])
    hand_frame = next(e for e in events if e["movement_class"]["name"] == "grasp")["start_frame"]
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(out), "-vf", f"select=eq(n\\,{hand_frame})", "-frames:v", "1",
                          "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"], capture_output=True, check=True).stdout  # fmt: skip
    img = np.frombuffer(raw, np.uint8).reshape(av["height"], av["width"], 3).astype(int)
    purple = (np.abs(img - np.array(SKELETON)).sum(axis=2) < 60).sum()
    assert purple > 200  # skeleton lines and joints are drawn on the hand

    # The video page's "Render annotated video": the latest runs, here as VP9 in WebM.
    again = client.post(f"/api/v1/videos/{video_id}/annotated", json={"codec": "vp9", "max_side": 480, "objects": False},
                        headers=h)  # fmt: skip
    assert again.status_code == 202 and again.json()["status"] == "building"
    drain(enqueued)
    webm = client.get(f"/api/v1/videos/{video_id}/annotated", headers=h).json()[0]
    assert webm["status"] == "ready" and webm["codec"] == "vp9" and max(webm["width"], webm["height"]) == 480
    assert webm["inputs"]["movement_run_id"] == result["movement"]["cv_run_id"] and webm["frames"] == frames
    assert (
        client.get(f"/api/v1/annotated-videos/{webm['id']}/download", headers=h)
        .json()["filename"]
        .endswith(".webm")
    )

    built = result["dataset"]
    version = client.get(f"/api/v1/datasets/versions/{built['dataset_version_id']}", headers=h).json()
    assert version["status"] == "ready" and version["sample_count"] == built["samples"] == len(events)
    assert version["spec"]["filters"]["video_ids"] == [video_id]
    exports = {e["format"]: e for e in result["export"]["exports"]}
    assert set(exports) == {"egolabs", "coco"} and all(e["sha256"] for e in exports.values())
    listed = client.get(
        "/api/v1/datasets/exports", params={"version_id": built["dataset_version_id"]}, headers=h
    ).json()
    assert {e["status"] for e in listed["items"]} == {"ready"}
