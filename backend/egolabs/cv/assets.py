"""Model files, fetched once from a pinned URL and verified by SHA-256 before use."""

import hashlib
import os
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from egolabs.config import get_settings


@dataclass(frozen=True)
class ModelAsset:
    name: str
    url: str
    sha256: str


HAND_LANDMARKER = ModelAsset(
    name="hand_landmarker.task",
    url="https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task",
    sha256="fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1",
)


EFFICIENTDET_LITE0 = ModelAsset(
    name="efficientdet_lite0.tflite",
    url="https://storage.googleapis.com/mediapipe-models/object_detector/efficientdet_lite0/float16/1/efficientdet_lite0.tflite",
    sha256="4b59100025bea1235a84c1038879a6cccc9f6c49f5e41144e91e74d99e780993",
)

# Baked into the image and cached in CI (see backend/Dockerfile).
PINNED = (HAND_LANDMARKER, EFFICIENTDET_LITE0)


class AssetError(Exception):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def cache_dir() -> Path:
    configured = get_settings().model_cache_dir
    return Path(configured) if configured else Path.home() / ".cache" / "egolabs" / "models"


def ensure(asset: ModelAsset, timeout: int = 120) -> Path:
    """Path to the verified model file, downloading it on first use."""
    path = cache_dir() / asset.sha256[:12] / asset.name
    if path.exists() and _sha256(path) == asset.sha256:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".part")
    try:
        with os.fdopen(fd, "wb") as out, urllib.request.urlopen(asset.url, timeout=timeout) as res:  # noqa: S310 - pinned https URL
            while block := res.read(1 << 20):
                out.write(block)
        got = _sha256(Path(tmp))
        if got != asset.sha256:
            raise AssetError(
                f"{asset.name}: checksum {got[:12]}… does not match the pinned {asset.sha256[:12]}…"
            )
        # mkstemp creates the file 0600; a shared cache (e.g. baked into an image as root) must be readable by all.
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except OSError as exc:
        raise AssetError(f"could not download {asset.name} from {asset.url}: {exc}") from exc
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return path
