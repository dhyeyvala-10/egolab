"""Phase 1 ingestion, end to end through the upload API and the worker handlers."""

import json
import uuid

import pytest
from sqlalchemy import func, select

from egolabs import storage
from egolabs.config import get_settings
from egolabs.ingest.probe import probe
from egolabs.models import Event, Job, JobStatus, LineageEdge, MetadataFile, Upload, UploadStatus, Video
from tests.conftest import auth_header, drain, register
from tests.media import make_clip, make_frames, make_zip, put_parts, upload_file

RAW = lambda: get_settings().s3_bucket_raw  # noqa: E731
DERIVED = lambda: get_settings().s3_bucket_derived  # noqa: E731


@pytest.fixture
def writer(client, admin):
    return auth_header(admin)


def _video_count(db) -> int:
    return db.scalar(select(func.count()).select_from(Video))


def test_video_upload_is_probed_stored_and_given_derivatives(client, db, writer, enqueued, tmp_path):
    clip = make_clip(
        tmp_path / "kitchen.mp4", seconds=2, fps=30, size="320x240", tags={"make": "GoPro", "model": "HERO12"}
    )
    upload = upload_file(client, writer, clip)
    assert upload["status"] == "processing"
    drain(enqueued)

    row = db.get(Upload, uuid.UUID(upload["id"]))
    assert row.status == UploadStatus.processed
    video = db.get(Video, row.video_id)
    expected = probe(clip)  # every stored value is what ffprobe reports
    assert (video.width, video.height, video.fps, video.frame_count, video.codec) == (
        expected.width, expected.height, expected.fps, expected.frame_count, expected.codec,
    )  # fmt: skip
    assert video.duration_s == expected.duration_s
    assert video.camera_metadata["make"] == "GoPro" and video.camera_metadata["model"] == "HERO12"
    assert video.status.value == "ready"
    assert video.storage_key == f"videos/{video.sha256[:2]}/{video.sha256}.mp4"
    assert storage.object_size(RAW(), video.storage_key) == clip.stat().st_size
    assert storage.object_size(RAW(), row.staging_key) is None  # staging copy removed after ingest
    assert storage.object_size(DERIVED(), video.proxy_key) and storage.object_size(
        DERIVED(), video.thumbnails_key
    )
    assert video.derivatives["proxy"]["frame_count"] == video.frame_count  # frame-exact proxy
    assert video.derivatives["proxy"]["height"] == 360

    edge = db.scalar(select(LineageEdge).where(LineageEdge.child_id == video.id))
    assert (edge.parent_type, edge.parent_id, edge.relation) == ("upload", row.id, "ingested_as")
    types = set(db.scalars(select(Event.type)))
    assert {"video.ingested", "video.ready", "upload.processed"} <= types
    jobs = db.scalars(select(Job).order_by(Job.created_at)).all()
    assert [j.type for j in jobs] == ["ingest.upload", "ingest.derivatives"]
    assert all(j.status == JobStatus.succeeded for j in jobs)
    assert jobs[1].parent_job_id == jobs[0].id


@pytest.mark.parametrize("ext", [".mov", ".avi", ".mkv"])
def test_other_containers(client, db, writer, enqueued, tmp_path, ext):
    clip = make_clip(tmp_path / f"clip{ext}", seconds=1, fps=25)
    upload_file(client, writer, clip)
    drain(enqueued)
    video = db.scalar(select(Video))
    assert video.status.value == "ready"
    assert video.fps == 25 and video.frame_count == 25


def test_same_file_twice_creates_one_video(client, db, writer, enqueued, tmp_path):
    clip = make_clip(tmp_path / "take.mp4")
    first = upload_file(client, writer, clip)
    drain(enqueued)
    second = upload_file(client, writer, clip, name="take-copy.mp4")
    drain(enqueued)

    assert _video_count(db) == 1
    up1, up2 = db.get(Upload, uuid.UUID(first["id"])), db.get(Upload, uuid.UUID(second["id"]))
    assert up1.status == UploadStatus.processed
    assert up2.status == UploadStatus.duplicate
    assert up2.video_id == up1.video_id  # linked to the existing record
    assert up2.result["duplicates"] == [{"name": "take-copy.mp4", "video_id": str(up1.video_id)}]
    assert db.scalar(select(LineageEdge).where(LineageEdge.parent_id == up2.id)).relation == "duplicate_of"
    assert db.scalar(select(func.count()).select_from(Job).where(Job.type == "ingest.derivatives")) == 1


def test_corrupt_file_is_flagged_not_crashed_on(client, db, writer, enqueued, tmp_path):
    bad = tmp_path / "broken.mp4"
    bad.write_bytes(b"\x00\x00\x00\x18ftypmp42" + bytes(range(256)) * 400)
    upload = upload_file(client, writer, bad)
    drain(enqueued)

    row = db.get(Upload, uuid.UUID(upload["id"]))
    assert row.status == UploadStatus.processed
    video = db.get(Video, row.video_id)
    assert video.status.value == "corrupt"
    assert video.error and "broken.mp4" in video.error and "/tmp" not in video.error
    assert video.width is None and video.fps is None  # nothing invented
    assert storage.object_size(RAW(), video.storage_key) == bad.stat().st_size  # raw kept as uploaded
    jobs = db.scalars(select(Job)).all()
    assert [(j.type, j.status) for j in jobs] == [("ingest.upload", JobStatus.succeeded)]
    assert db.scalar(select(Event).where(Event.type == "video.corrupt")) is not None

    # The same corrupt bytes again are still a duplicate, not a second record.
    upload_file(client, writer, bad, name="broken-again.mp4")
    drain(enqueued)
    assert _video_count(db) == 1


def test_damage_found_while_building_the_proxy_marks_video_corrupt(
    client, db, writer, enqueued, tmp_path, monkeypatch
):
    from egolabs.ingest import pipeline
    from egolabs.ingest.media import MediaError

    def fail(*_, **__):
        raise MediaError("Invalid NAL unit size")

    monkeypatch.setattr(pipeline, "make_proxy", fail)
    upload_file(client, writer, make_clip(tmp_path / "late-damage.mp4"))
    drain(enqueued)
    video = db.scalar(select(Video))
    assert video.status.value == "corrupt" and "NAL" in video.error
    derive = db.scalar(select(Job).where(Job.type == "ingest.derivatives"))
    assert derive.status == JobStatus.failed


def test_archive_with_videos_sequence_and_sidecars(client, db, writer, enqueued, tmp_path):
    session = client.post("/api/v1/sessions", json={"task": "pick and place"}, headers=writer).json()
    existing = make_clip(tmp_path / "existing.mp4", pattern="smptebars")
    upload_file(client, writer, existing, session_id=session["id"])
    drain(enqueued)

    new = make_clip(tmp_path / "new.mov", fps=24)
    frames = make_frames(tmp_path / "frames", 12)
    members = {
        "take1/new.mov": new,
        "take1/new.json": json.dumps({"lighting": "low", "hand": "right"}).encode(),
        "dup/existing.mp4": existing,
        "cam2/": b"",
        **{f"cam2/{f.name}": f for f in frames},
        "notes.csv": b"t,event\n0.5,grasp\n1.0,release\n",
        "readme.txt": b"ignored",
        "__MACOSX/._new.mov": b"junk",
    }
    archive = make_zip(tmp_path / "session.zip", {k: v for k, v in members.items() if not k.endswith("/")})
    upload = upload_file(client, writer, archive, session_id=session["id"], sequence_fps=10)
    drain(enqueued)

    row = db.get(Upload, uuid.UUID(upload["id"]))
    assert row.status == UploadStatus.processed, row.error
    assert len(row.result["created"]) == 2  # new.mov + the image sequence
    assert [d["name"] for d in row.result["duplicates"]] == ["dup/existing.mp4"]
    assert row.result["skipped"] == ["readme.txt"]

    videos = {v.source_kind.value: v for v in db.scalars(select(Video).where(Video.upload_id == row.id))}
    member = videos["archive_member"]
    assert member.source_path == "take1/new.mov" and member.fps == 24 and member.status.value == "ready"
    seq = videos["image_sequence"]
    assert seq.frame_count == 12 and seq.fps == 10 and seq.duration_s == 1.2
    assert (seq.width, seq.height) == (64, 48)
    assert seq.status.value == "ready" and seq.derivatives["proxy"]["frame_count"] == 12
    assert len(storage.list_keys(RAW(), seq.storage_key)) == 12
    assert all(v.session_id == uuid.UUID(session["id"]) for v in videos.values())

    sidecars = {s.filename: s for s in db.scalars(select(MetadataFile))}
    assert sidecars["new.json"].video_id == member.id  # same stem → attached to that video
    assert sidecars["new.json"].parsed == {"lighting": "low", "hand": "right"}
    assert sidecars["notes.csv"].video_id is None  # session-level
    assert sidecars["notes.csv"].parsed == [{"t": "0.5", "event": "grasp"}, {"t": "1.0", "event": "release"}]
    assert storage.object_size(
        RAW(), f"archives/{storage.sha256_file(archive)[:2]}/{storage.sha256_file(archive)}.zip"
    )


def test_image_sequence_without_a_frame_rate_keeps_it_unknown(client, db, writer, enqueued, tmp_path):
    frames = make_frames(tmp_path / "f", 5, ext=".jpg")
    archive = make_zip(tmp_path / "seq.zip", {f.name: f for f in frames})
    upload_file(client, writer, archive)
    drain(enqueued)
    video = db.scalar(select(Video))
    assert video.source_kind.value == "image_sequence"
    assert video.frame_count == 5 and video.fps is None and video.duration_s is None
    assert video.status.value == "ready"


def test_standalone_sidecar_attaches_to_matching_session_video(client, db, writer, enqueued, tmp_path):
    session = client.post("/api/v1/sessions", json={}, headers=writer).json()
    upload_file(client, writer, make_clip(tmp_path / "GX010042.mp4"), session_id=session["id"])
    drain(enqueued)
    meta = tmp_path / "GX010042.json"
    meta.write_text(json.dumps({"imu_hz": 200}))
    upload_file(client, writer, meta, session_id=session["id"])
    bad = tmp_path / "broken.json"
    bad.write_text("{not json")
    upload_file(client, writer, bad, session_id=session["id"])
    drain(enqueued)

    video = db.scalar(select(Video))
    good = db.scalar(select(MetadataFile).where(MetadataFile.filename == "GX010042.json"))
    assert good.video_id == video.id and good.parsed == {"imu_hz": 200}
    broken = db.scalar(select(MetadataFile).where(MetadataFile.filename == "broken.json"))
    assert broken.parsed is None and "invalid JSON" in broken.error  # stored raw, flagged


def test_archive_with_path_traversal_is_rejected(client, db, writer, enqueued, tmp_path):
    archive = make_zip(tmp_path / "evil.zip", {"../../etc/passwd.json": b"{}"})
    upload = upload_file(client, writer, archive)
    drain(enqueued)
    row = db.get(Upload, uuid.UUID(upload["id"]))
    assert row.status == UploadStatus.failed and "unsafe path" in row.error
    assert _video_count(db) == 0


def test_not_a_zip_fails_cleanly(client, db, writer, enqueued, tmp_path):
    fake = tmp_path / "fake.zip"
    fake.write_bytes(b"not a zip at all")
    upload = upload_file(client, writer, fake)
    drain(enqueued)
    assert db.get(Upload, uuid.UUID(upload["id"])).status == UploadStatus.failed


# --- the upload API ---------------------------------------------------------------------------------


def test_unsupported_types_and_roles(client, admin, viewer):
    res = client.post(
        "/api/v1/uploads", json={"filename": "notes.txt", "size_bytes": 3}, headers=auth_header(admin)
    )
    assert res.status_code == 422 and ".mp4" in res.json()["detail"]
    res = client.post(
        "/api/v1/uploads", json={"filename": "a.mp4", "size_bytes": 3}, headers=auth_header(viewer)
    )
    assert res.status_code == 403
    missing = {"filename": "a.mp4", "size_bytes": 3, "session_id": str(uuid.uuid4())}
    assert client.post("/api/v1/uploads", json=missing, headers=auth_header(admin)).status_code == 422


def test_interrupted_upload_resumes_from_stored_parts(client, db, writer, enqueued, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "upload_part_size_bytes", 5 * 1024 * 1024)
    clip = make_clip(tmp_path / "long.mp4", seconds=1)
    data = clip.read_bytes() + b"\x00" * (6 * 1024 * 1024)  # padded past one part; still a valid MP4 prefix
    path = tmp_path / "padded.mp4"
    path.write_bytes(data)
    upload = client.post(
        "/api/v1/uploads", json={"filename": "padded.mp4", "size_bytes": len(data)}, headers=writer
    ).json()
    assert upload["part_count"] == 2

    put_parts(client, writer, upload, data, [1])  # then the browser tab closes
    state = client.get(f"/api/v1/uploads/{upload['id']}", headers=writer).json()
    assert [p["part_number"] for p in state["uploaded_parts"]] == [1]

    put_parts(client, writer, upload, data, [2])  # resumed: only the missing part
    parts = [
        {"part_number": p["part_number"], "etag": p["etag"]}
        for p in client.get(f"/api/v1/uploads/{upload['id']}", headers=writer).json()["uploaded_parts"]
    ]
    incomplete = client.post(
        f"/api/v1/uploads/{upload['id']}/complete", json={"parts": parts[:1]}, headers=writer
    )
    assert incomplete.status_code == 422
    done = client.post(f"/api/v1/uploads/{upload['id']}/complete", json={"parts": parts}, headers=writer)
    assert done.status_code == 202
    drain(enqueued)
    assert db.get(Upload, uuid.UUID(upload["id"])).video_id is not None
    assert db.scalar(select(Video)).size_bytes == len(data)


def test_only_the_uploader_or_an_admin_can_change_an_upload(client, admin, enqueued, tmp_path):
    annotator = register(client, "annotator@example.com")
    client.patch(
        f"/api/v1/users/{annotator['user']['id']}", json={"role": "annotator"}, headers=auth_header(admin)
    ).raise_for_status()
    other = register(client, "other@example.com")
    client.patch(
        f"/api/v1/users/{other['user']['id']}", json={"role": "annotator"}, headers=auth_header(admin)
    ).raise_for_status()

    upload = client.post(
        "/api/v1/uploads", json={"filename": "x.mp4", "size_bytes": 10}, headers=auth_header(annotator)
    ).json()
    assert (
        client.post(
            f"/api/v1/uploads/{upload['id']}/parts", json={"part_numbers": [1]}, headers=auth_header(other)
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/uploads/{upload['id']}/parts",
            json={"part_numbers": [2]},
            headers=auth_header(annotator),
        ).status_code
        == 422
    )
    assert client.delete(f"/api/v1/uploads/{upload['id']}", headers=auth_header(admin)).status_code == 204
    after = client.get(f"/api/v1/uploads/{upload['id']}", headers=auth_header(annotator)).json()
    assert after["status"] == "aborted"
    assert (
        client.post(
            f"/api/v1/uploads/{upload['id']}/parts",
            json={"part_numbers": [1]},
            headers=auth_header(annotator),
        ).status_code
        == 409
    )


def test_list_uploads_filters(client, writer, enqueued, tmp_path):
    session = client.post("/api/v1/sessions", json={}, headers=writer).json()
    upload_file(client, writer, make_clip(tmp_path / "a.mp4"), session_id=session["id"])
    client.post("/api/v1/uploads", json={"filename": "b.mp4", "size_bytes": 5}, headers=writer)
    everything = client.get("/api/v1/uploads", headers=writer).json()
    assert everything["total"] == 2
    in_session = client.get("/api/v1/uploads", params={"session_id": session["id"]}, headers=writer).json()
    assert [u["filename"] for u in in_session["items"]] == ["a.mp4"]
    uploading = client.get("/api/v1/uploads", params={"status": "uploading"}, headers=writer).json()
    assert [u["filename"] for u in uploading["items"]] == ["b.mp4"]
