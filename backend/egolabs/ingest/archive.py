"""Safe ZIP extraction and classification of archive members."""

import re
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from egolabs.ingest.formats import IMAGE_EXTENSIONS, SIDECAR_EXTENSIONS, VIDEO_EXTENSIONS, extension


class ArchiveError(Exception):
    pass


@dataclass
class ArchiveContents:
    videos: list[tuple[str, Path]] = field(default_factory=list)  # (path in archive, extracted file)
    sequences: list[tuple[str, list[Path]]] = field(default_factory=list)  # (folder, frames in order)
    sidecars: list[tuple[str, Path]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def _natural_key(name: str) -> list[object]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", name)]


def _ignored(name: str) -> bool:
    parts = PurePosixPath(name).parts
    return any(p.startswith(".") or p == "__MACOSX" for p in parts)


def extract(archive: Path, dest: Path, max_uncompressed_bytes: int) -> ArchiveContents:
    """
    Extract supported members. Rejects path traversal and archives whose declared uncompressed size is
    over the limit (zip bombs). Folders holding two or more images become image sequences.
    """
    try:
        zf = zipfile.ZipFile(archive)
    except zipfile.BadZipFile as exc:
        raise ArchiveError(f"not a valid ZIP archive: {exc}") from exc

    contents = ArchiveContents()
    with zf:
        members = [m for m in zf.infolist() if not m.is_dir()]
        total = sum(m.file_size for m in members)
        if total > max_uncompressed_bytes:
            raise ArchiveError(
                f"archive expands to {total} bytes, over the {max_uncompressed_bytes} byte limit"
            )

        images: dict[str, list[tuple[str, Path]]] = defaultdict(list)
        for index, member in enumerate(members):
            name = member.filename.replace("\\", "/")
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts:
                raise ArchiveError(f"unsafe path in archive: {name}")
            if _ignored(name):
                continue
            ext = extension(name)
            if ext not in VIDEO_EXTENSIONS | IMAGE_EXTENSIONS | SIDECAR_EXTENSIONS:
                contents.skipped.append(name)
                continue
            target = dest / f"{index:06d}{ext}"
            with zf.open(member) as src, target.open("wb") as out:
                while block := src.read(8 * 1024 * 1024):
                    out.write(block)
            if ext in VIDEO_EXTENSIONS:
                contents.videos.append((name, target))
            elif ext in SIDECAR_EXTENSIONS:
                contents.sidecars.append((name, target))
            else:
                images[str(path.parent)].append((name, target))

    for folder, frames in sorted(images.items()):
        if len(frames) < 2:
            contents.skipped.extend(name for name, _ in frames)
            continue
        frames.sort(key=lambda f: _natural_key(f[0]))
        contents.sequences.append((folder, [p for _, p in frames]))
    return contents
