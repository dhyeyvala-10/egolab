"""
Exports and lineage on real output (spec Phase 6): a clip with known motion goes through upload, hand
tracking, object detection, and movement classification (real MediaPipe models), some events are reviewed
and corrected, a version is built, and it is exported in every format. Each export is read back and checked
against the version: sample counts, the content hash in the manifest, keypoints from the hand run's Parquet,
key-frame images decoded from the raw video, and the raw file's sha256. Every sample's lineage reaches the
raw file.
"""

import hashlib
import io
import json
import tarfile
import uuid
import zipfile

import httpx
import pyarrow.parquet as pq
import pytest

from egolabs import storage
from egolabs.config import get_settings
from egolabs.cv import samples
from egolabs.models import DatasetExport, Upload
from tests.conftest import auth_header, drain
from tests.media import upload_file

D = "/api/v1/datasets"
FORMATS = ("jsonl", "parquet", "coco", "webdataset", "egolabs")


@pytest.fixture
def h(admin):
    return auth_header(admin)


@pytest.fixture(scope="module")
def grasp(tmp_path_factory):
    return samples.make_scene_clip(tmp_path_factory.mktemp("ds") / "grasp.mp4", samples.grasp_scene())


def _zip(export: dict) -> zipfile.ZipFile:
    return zipfile.ZipFile(
        io.BytesIO(storage.get_bytes(get_settings().s3_bucket_derived, export["storage_key"]))
    )


def test_exports_and_lineage_of_a_real_version(client, db, h, enqueued, grasp):
    sess = client.post("/api/v1/sessions", json={"environment": "kitchen", "task": "grasp"}, headers=h).json()
    up = upload_file(client, h, grasp.path, session_id=sess["id"])
    drain(enqueued)
    video_id = str(db.get(Upload, uuid.UUID(up["id"])).video_id)
    video = client.get(f"/api/v1/videos/{video_id}", headers=h).json()
    assert client.post("/api/v1/cv/runs", json={"video_ids": [video_id]}, headers=h).status_code == 201
    drain(enqueued)
    events = client.get(
        "/api/v1/movement/events", params={"video_id": video_id, "limit": 100}, headers=h
    ).json()["items"]
    assert len(events) >= 5
    for e in events[:3]:
        client.post(f"/api/v1/review/events/{e['id']}/status", json={"status": "confirmed"}, headers=h)
    grasp_event = next(e for e in events if e["movement_class"]["name"] == "grasp")
    client.post(f"/api/v1/review/events/{grasp_event['id']}/correct", json={"class": "pinch"}, headers=h)

    ds = client.post(D, json={"name": "Grasp demo"}, headers=h).json()["id"]
    spec = {"filters": {"statuses": ["confirmed", "auto_detected", "needs_review"]},
            "split": {"train": 0.6, "val": 0.2, "test": 0.2, "group_by": "sample", "seed": 11}}  # fmt: skip
    vid = client.post(f"{D}/{ds}/versions", json={"spec": spec}, headers=h).json()["id"]
    drain(enqueued)
    version = client.get(f"{D}/versions/{vid}", headers=h).json()
    assert version["status"] == "ready", version["error"]
    rows = client.get(f"{D}/versions/{vid}/samples", params={"limit": 500}, headers=h).json()["items"]
    n = version["sample_count"]
    assert n == len(rows) == len(events)  # every event, the grasp replaced by its correction
    assert "pinch" in {r["class_name"] for r in rows} and "grasp" not in {r["class_name"] for r in rows}
    by_id = {r["id"]: r for r in rows}

    exports = {}
    for fmt in FORMATS:
        res = client.post(f"{D}/versions/{vid}/exports", json={"format": fmt}, headers=h)
        assert res.status_code == 202, res.text
        exports[fmt] = res.json()["id"]
    drain(enqueued)
    listed = {
        e["format"]: e
        for e in client.get(f"{D}/exports", params={"version_id": vid}, headers=h).json()["items"]
    }
    assert set(listed) == set(FORMATS) and all(e["status"] == "ready" for e in listed.values()), listed
    by_status = lambda s: client.get(f"{D}/exports", params={"status": s}, headers=h).json()["total"]  # noqa: E731
    assert (by_status("ready"), by_status("failed")) == (len(FORMATS), 0)
    stored = {
        fmt: {"storage_key": db.get(DatasetExport, uuid.UUID(i)).storage_key} for fmt, i in exports.items()
    }

    # JSON Lines: one line per sample, with keypoints from the hand run and the raw file's identity.
    z = _zip(stored["jsonl"])
    lines = [json.loads(x) for x in z.read("samples.jsonl").decode().splitlines()]
    manifest = json.loads(z.read("manifest.json"))
    assert len(lines) == n and manifest["version"]["content_hash"] == version["content_hash"]
    assert manifest["keypoint_schema"]["name"] == "hand-21" and manifest["model_versions"]
    for rec in lines:
        s = by_id[rec["sample_id"]]
        assert (rec["class"], rec["start_frame"], rec["end_frame"], rec["split"]) == (
            s["class_name"],
            s["start_frame"],
            s["end_frame"],
            s["split"],
        )
        assert rec["video"]["sha256"] == video["sha256"]
        assert rec["keypoints"], rec["class"]  # the hand is tracked through every event of this clip
        assert all(
            s["start_frame"] <= k["frame"] <= s["end_frame"] and len(k["kp_x"]) == 21
            for k in rec["keypoints"]
        )

    # Parquet: samples, one keypoint row per sample frame, object boxes.
    z = _zip(stored["parquet"])
    st = pq.read_table(io.BytesIO(z.read("samples.parquet")))
    kp = pq.read_table(io.BytesIO(z.read("keypoints.parquet")))
    ob = pq.read_table(io.BytesIO(z.read("objects.parquet")))
    assert st.num_rows == n and kp.num_rows == sum(len(r["keypoints"]) for r in lines)
    assert ob.num_rows == sum(len(r["object_boxes"]) for r in lines) > 0
    assert set(st.column("video_sha256").to_pylist()) == {video["sha256"]}

    # COCO: per-split annotation files, one decoded key frame per sample, 21 keypoints in pixels.
    z = _zip(stored["coco"])
    anns, images = [], []
    for split in ("train", "val", "test"):
        doc = json.loads(z.read(f"annotations/{split}.json"))
        assert (
            len(doc["categories"][0]["keypoints"]) == 21
            and doc["info"]["content_hash"] == version["content_hash"]
        )
        anns += doc["annotations"]
        images += doc["images"]
        assert all(by_id[a["attributes"]["sample_id"]]["split"] == split for a in doc["annotations"])
    assert len(anns) == len(images) == n
    for img in images:
        data = z.read(img["file_name"])
        assert data[:2] == b"\xff\xd8" and (img["width"], img["height"]) == (video["width"], video["height"])
    assert all(a["num_keypoints"] == 21 and len(a["keypoints"]) == 63 for a in anns)
    assert all(
        0 <= a["keypoints"][0] <= video["width"] and 0 <= a["keypoints"][1] <= video["height"] for a in anns
    )

    # WebDataset: shards per split, each sample a .json, a .jpg, and its keypoints.
    z = _zip(stored["webdataset"])
    keys: dict[str, set[str]] = {}
    for name in z.namelist():
        if name.endswith(".tar"):
            with tarfile.open(fileobj=io.BytesIO(z.read(name))) as t:
                for m in t.getmembers():
                    key, ext = m.name.split(".", 1)
                    keys.setdefault(key, set()).add(ext)
    assert len(keys) == n and all(exts == {"json", "jpg", "keypoints.json"} for exts in keys.values())

    # Native: manifest, samples, keypoints, evidence, raw-file provenance, splits.
    z = _zip(stored["egolabs"])
    names = set(z.namelist())
    assert {"manifest.json", "samples.parquet", "keypoints.parquet", "objects.parquet", "evidence.jsonl",
            "videos.json", "splits/train.txt", "splits/val.txt", "splits/test.txt"} <= names  # fmt: skip
    vids = json.loads(z.read("videos.json"))
    assert vids[0]["sha256"] == video["sha256"] and vids[0]["session"]["environment"] == "kitchen"
    split_ids = {s: set(z.read(f"splits/{s}.txt").decode().split()) for s in ("train", "val", "test")}
    assert set().union(*split_ids.values()) == set(by_id) and sum(map(len, split_ids.values())) == n
    evidence = [json.loads(x) for x in z.read("evidence.jsonl").decode().splitlines()]
    assert len(evidence) == n and all(e["frames"] for e in evidence)

    # The download link is served straight from storage and carries the recorded checksum.
    link = client.get(f"{D}/exports/{exports['egolabs']}/download", headers=h).json()
    body = httpx.get(link["url"]).content
    assert hashlib.sha256(body).hexdigest() == listed["egolabs"]["sha256"] and link["filename"].endswith(
        "-egolabs.zip"
    )

    # Lineage from every sample reaches the raw file, via the runs that produced it.
    for s in rows:
        g = client.get(f"{D}/samples/{s['id']}/lineage", headers=h).json()
        assert g["reaches_raw_file"]
        raw = next(x for x in g["nodes"] if x["type"] == "raw_file")
        assert raw["detail"]["sha256"] == video["sha256"]
        kinds = {x["detail"].get("kind") for x in g["nodes"] if x["type"] == "cv_run"}
        assert kinds == {"hand_tracking", "object_detection", "movement"}
        assert any(x["type"] == "upload" for x in g["nodes"]) and any(x["type"] == "job" for x in g["nodes"])
