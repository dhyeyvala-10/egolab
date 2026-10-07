"""Frames for dataset exports: exactly the frames asked for, however many, even where ffmpeg rejects a long
`select` expression (it did on a real server: "Error while parsing expression")."""

import subprocess
import uuid

from egolabs.datasets import export
from egolabs.models import Upload, Video
from tests.conftest import auth_header, drain
from tests.media import make_numbered_clip, read_barcodes, upload_file


def _video(client, db, admin, enqueued, tmp_path, frames: int) -> Video:
    up = upload_file(client, auth_header(admin), make_numbered_clip(tmp_path / "numbered.mp4", frames))
    drain(enqueued)
    db.expire_all()
    return db.get(Video, db.get(Upload, uuid.UUID(up["id"])).video_id)


def _shown(images: dict[int, bytes], tmp_path) -> dict[int, int]:
    """The number each extracted JPEG shows."""
    out = {}
    for f, jpg in images.items():
        path = tmp_path / f"f{f}.jpg"
        path.write_bytes(jpg)
        (n,) = read_barcodes(path)
        out[f] = n
    return out


def test_select_expressions_stay_short():
    assert export.select_expr([5]) == "eq(n\\,5)"
    assert export.select_expr([1, 2, 3, 7, 9, 10]) == "between(n\\,1\\,3)+eq(n\\,7)+between(n\\,9\\,10)"


def test_many_scattered_frames_are_extracted_exactly(client, db, admin, enqueued, tmp_path):
    video = _video(client, db, admin, enqueued, tmp_path, 300)
    wanted = {*range(0, 300, 3), 1, 2, 150, 151, 152, 299}  # more than one batch, with runs and gaps
    images = export.extract_images(video, wanted, tmp_path)
    assert set(images) == wanted
    assert _shown(images, tmp_path) == {f: f for f in wanted}


def test_a_rejected_expression_is_split_until_ffmpeg_takes_it(
    client, db, admin, enqueued, tmp_path, monkeypatch
):
    video = _video(client, db, admin, enqueued, tmp_path, 120)
    real_run = subprocess.run
    calls = []

    def picky_ffmpeg(cmd, *args, **kwargs):  # like a build whose parser gives up past a few terms
        expr = next((c for c in cmd if isinstance(c, str) and c.startswith("select=")), "")
        calls.append(expr.count("+") + 1)
        if expr.count("+") + 1 > 3:
            return subprocess.CompletedProcess(cmd, 1, b"", b"Error while parsing expression")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(export.subprocess, "run", picky_ffmpeg)
    wanted = set(range(0, 120, 5))  # 24 separate frames: 24 terms
    images = export.extract_images(video, wanted, tmp_path)
    assert _shown(images, tmp_path) == {f: f for f in wanted}
    assert max(calls) == 24 and min(calls) <= 3
