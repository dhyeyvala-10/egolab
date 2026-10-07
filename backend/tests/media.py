"""Test media made with ffmpeg on the fly (no binary fixtures in the repo)."""

import subprocess
import zipfile
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

CODECS = {".mp4": ["-c:v", "libx264", "-pix_fmt", "yuv420p"], ".mov": ["-c:v", "libx264", "-pix_fmt", "yuv420p"],
          ".mkv": ["-c:v", "libx264", "-pix_fmt", "yuv420p"], ".avi": ["-c:v", "mpeg4"]}  # fmt: skip


def make_clip(path: Path, seconds: float = 1.0, fps: int = 30, size: str = "320x240", tags: dict | None = None,
              pattern: str = "testsrc") -> Path:  # fmt: skip
    args = [
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"{pattern}=size={size}:rate={fps}",
        "-t",
        str(seconds),
    ]
    args += CODECS[path.suffix]
    if path.suffix in (".mp4", ".mov"):
        args += ["-movflags", "+use_metadata_tags"]
    for key, value in (tags or {}).items():
        args += ["-metadata", f"{key}={value}"]
    subprocess.run([*args, str(path)], check=True)
    return path


def make_frames(folder: Path, count: int, ext: str = ".png", size: str = "64x48") -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size={size}:rate=10", "-frames:v", str(count),
         str(folder / f"frame_%03d{ext}")],
        check=True,
    )  # fmt: skip
    return sorted(folder.iterdir())


def make_zip(path: Path, members: dict[str, Path | bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in members.items():
            if isinstance(content, Path):
                zf.write(content, name)
            else:
                zf.writestr(name, content)
    return path


def upload_file(client: TestClient, headers: dict, path: Path, *, session_id: str | None = None,
                sequence_fps: float | None = None, name: str | None = None) -> dict:  # fmt: skip
    """Drive the browser flow: create → presigned PUT per part → complete. Returns the upload after completing."""
    data = path.read_bytes()
    body = {
        "filename": name or path.name,
        "size_bytes": len(data),
        "session_id": session_id,
        "sequence_fps": sequence_fps,
    }
    created = client.post("/api/v1/uploads", json=body, headers=headers)
    assert created.status_code == 201, created.text
    upload = created.json()
    parts = put_parts(client, headers, upload, data, range(1, upload["part_count"] + 1))
    done = client.post(f"/api/v1/uploads/{upload['id']}/complete", json={"parts": parts}, headers=headers)
    assert done.status_code == 202, done.text
    return done.json()


def put_parts(client: TestClient, headers: dict, upload: dict, data: bytes, numbers) -> list[dict]:
    numbers = list(numbers)
    urls = client.post(
        f"/api/v1/uploads/{upload['id']}/parts", json={"part_numbers": numbers}, headers=headers
    )
    assert urls.status_code == 200, urls.text
    size = upload["part_size"]
    parts = []
    for item in urls.json()["urls"]:
        n = item["part_number"]
        res = httpx.put(item["url"], content=data[(n - 1) * size : n * size])
        assert res.status_code == 200, res.text
        parts.append({"part_number": n, "etag": res.headers["etag"]})
    return parts


# --- frame-numbered clips: each frame shows its own index as a 16-bit barcode ----------------------

BARCODE_BITS = 16
NUMBERED_SIZE = (320, 180)


def _barcode_frame(n: int, width: int, height: int) -> bytes:
    cell = width // BARCODE_BITS
    row = b"".join(
        (b"\xff" if (n >> (BARCODE_BITS - 1 - i)) & 1 else b"\x00") * cell for i in range(BARCODE_BITS)
    )
    return row.ljust(width, b"\x80") * height


def make_numbered_clip(path: Path, frames: int, fps: int = 30, vfr_after: int | None = None) -> Path:
    """
    A clip whose frame N shows N as black/white bars. With `vfr_after`, frames from that index on are
    spaced twice as far apart (a variable frame rate video).
    """
    width, height = NUMBERED_SIZE
    pts = (
        f"N/{fps}/TB"
        if vfr_after is None
        else f"if(lt(N\\,{vfr_after})\\,N/{fps}\\,{vfr_after}/{fps}+(N-{vfr_after})*2/{fps})/TB"
    )
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{width}x{height}",
         "-r", str(fps), "-i", "-", "-vf", f"setpts={pts}", "-fps_mode", "passthrough",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-g", "15", "-crf", "18", str(path)],
        input=b"".join(_barcode_frame(n, width, height) for n in range(frames)),
        capture_output=True,
        check=False,
    )  # fmt: skip
    assert proc.returncode == 0, proc.stderr.decode()
    return path


def read_barcodes(path: Path) -> list[int]:
    """Decode every frame of a video, in presentation order, and read the number each one shows."""
    info = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip().split(",")  # fmt: skip
    width, height = int(info[0]), int(info[1])
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-fps_mode", "passthrough", "-f", "rawvideo",
         "-pix_fmt", "gray", "-"],
        capture_output=True, check=True,
    ).stdout  # fmt: skip
    size = width * height
    out = []
    cell = width * (NUMBERED_SIZE[0] // BARCODE_BITS) / NUMBERED_SIZE[0]
    for f in range(len(raw) // size):
        frame = raw[f * size : (f + 1) * size]
        mid = (height // 2) * width
        n = 0
        for i in range(BARCODE_BITS):
            n = (n << 1) | (frame[mid + int((i + 0.5) * cell)] > 128)
        out.append(n)
    return out
