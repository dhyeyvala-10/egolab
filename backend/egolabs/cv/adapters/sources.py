"""Reading precomputed model output (JSON Lines) from a local path or `s3://bucket/key`."""

from pathlib import Path

from egolabs.cv.adapters.base import AdapterError, VideoContext


def resolve(template: str, video: VideoContext) -> str:
    """`{sha256}` and `{video_id}` in a configured source, filled in for this video."""
    return template.format(sha256=video.sha256, video_id=video.video_id)


def read_text(source: str) -> str:
    if source.startswith("s3://"):
        from egolabs import storage

        bucket, _, key = source[5:].partition("/")
        try:
            return storage.get_bytes(bucket, key).decode()
        except Exception as exc:
            raise AdapterError(f"can't read {source}: {exc}") from exc
    try:
        return Path(source).read_text()
    except OSError as exc:
        raise AdapterError(f"can't read {source}: {exc}") from exc
