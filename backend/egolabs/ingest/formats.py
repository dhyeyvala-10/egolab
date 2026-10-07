from pathlib import PurePosixPath

from egolabs.models import UploadKind

VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}
ARCHIVE_EXTENSIONS = {".zip"}
SIDECAR_EXTENSIONS = {".json", ".csv"}

CONTENT_TYPES = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
    ".zip": "application/zip",
    ".json": "application/json",
    ".csv": "text/csv",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".bmp": "image/bmp",
}

SUPPORTED_UPLOAD_EXTENSIONS = VIDEO_EXTENSIONS | ARCHIVE_EXTENSIONS | SIDECAR_EXTENSIONS


def extension(name: str) -> str:
    return PurePosixPath(name).suffix.lower()


def upload_kind(filename: str) -> UploadKind | None:
    ext = extension(filename)
    if ext in VIDEO_EXTENSIONS:
        return UploadKind.video
    if ext in ARCHIVE_EXTENSIONS:
        return UploadKind.archive
    if ext in SIDECAR_EXTENSIONS:
        return UploadKind.sidecar
    return None
