"""Frame-exact seeking (spec Phase 2): the proxy plus its frame index put frame N at frame N."""

import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from egolabs import storage
from egolabs.config import get_settings
from egolabs.ingest import frame_index
from egolabs.models import Job, JobStatus, Upload, Video
from tests.conftest import auth_header, drain
from tests.media import make_numbered_clip, read_barcodes, upload_file


@pytest.fixture
def h(admin):
    return auth_header(admin)


def _ingest(client, db, h, enqueued, clip: Path) -> Video:
    upload = upload_file(client, h, clip)
    drain(enqueued)
    return db.get(Video, db.get(Upload, uuid.UUID(upload["id"])).video_id)


def _proxy(video: Video, tmp_path: Path) -> Path:
    dest = tmp_path / "proxy.mp4"
    storage.download(get_settings().s3_bucket_derived, video.proxy_key, dest)
    return dest


@pytest.mark.parametrize("vfr_after", [None, 40], ids=["constant-rate", "variable-rate"])
def test_frame_n_shows_frame_n(client, db, h, enqueued, tmp_path, vfr_after):
    frames = 120
    video = _ingest(
        client, db, h, enqueued, make_numbered_clip(tmp_path / "numbered.mp4", frames, vfr_after=vfr_after)
    )
    assert video.frame_count == frames

    res = client.get(f"/api/v1/videos/{video.id}/frame-index", headers=h)
    assert res.status_code == 200, res.text
    index = res.json()
    assert index["frame_count"] == frames
    times = frame_index.timestamps(index)
    assert all(b > a for a, b in zip(times, times[1:], strict=False))  # strictly increasing
    if vfr_after is None:
        assert len(index["runs"]) == 1  # constant rate: one run, however long the video
    else:
        assert len(index["runs"]) > 1

    # Decode the proxy the inspector plays: its i-th frame in presentation order shows the number i.
    assert read_barcodes(_proxy(video, tmp_path)) == list(range(frames))

    # Seeking to frame N lands inside N's display interval, so the frame on screen is N.
    for n in range(frames):
        t = frame_index.seek_time(times, n)
        shown = max(i for i, ts in enumerate(times) if ts <= t)
        assert shown == n


def test_run_length_encoding_round_trips():
    for pts in ([0], [0, 512], [0, 512, 1024, 2048, 2560, 3072], list(range(0, 54000 * 512, 512))):
        runs = frame_index.encode_runs(pts)
        assert frame_index.decode_runs(runs) == pts
    assert frame_index.encode_runs(list(range(0, 54000 * 512, 512))) == [[0, 512, 54000]]


def test_frame_index_missing_then_rebuilt(client, db, h, enqueued, tmp_path):
    video = _ingest(client, db, h, enqueued, make_numbered_clip(tmp_path / "old.mp4", 30))
    # A video ingested before the frame index existed.
    storage.delete(get_settings().s3_bucket_derived, video.derivatives["frame_index"]["key"])
    video.derivatives = {k: v for k, v in video.derivatives.items() if k != "frame_index"}
    db.commit()
    assert client.get(f"/api/v1/videos/{video.id}/frame-index", headers=h).status_code == 404

    res = client.post(f"/api/v1/videos/{video.id}/frame-index", headers=h)
    assert res.status_code == 202, res.text
    drain(enqueued)
    job = db.get(Job, uuid.UUID(res.json()["job_id"]))
    assert (job.type, job.status) == ("video.frame_index", JobStatus.succeeded)
    index = client.get(f"/api/v1/videos/{video.id}/frame-index", headers=h).json()
    assert index["frame_count"] == 30
    assert client.get(f"/api/v1/videos/{uuid.uuid4()}/frame-index", headers=h).status_code == 404


def test_frame_index_needs_a_proxy_and_a_writer(client, db, h, viewer, enqueued, tmp_path):
    video = Video(original_filename="x.mp4", storage_key="videos/x.mp4", sha256="0" * 64, size_bytes=1)
    db.add(video)
    db.commit()
    assert client.post(f"/api/v1/videos/{video.id}/frame-index", headers=h).status_code == 409
    assert (
        client.post(f"/api/v1/videos/{video.id}/frame-index", headers=auth_header(viewer)).status_code == 403
    )


def test_stored_index_is_compact_json(client, db, h, enqueued, tmp_path):
    video = _ingest(client, db, h, enqueued, make_numbered_clip(tmp_path / "c.mp4", 60))
    body = storage.get_bytes(get_settings().s3_bucket_derived, video.derivatives["frame_index"]["key"])
    assert json.loads(body)["runs"] == [[0, 512, 60]]
    assert video.derivatives["frame_index"]["frame_count"] == 60
    assert (
        db.scalar(select(Video.derivatives["proxy"]["b_frames"].as_integer()).where(Video.id == video.id))
        == 0
    )
