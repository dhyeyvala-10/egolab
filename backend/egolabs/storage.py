"""
S3-compatible object storage (MinIO locally).

Raw objects are content-addressed (keyed by SHA-256) and written once: `put_raw` never overwrites an
existing object, so a raw file can't be replaced or lost by a later upload (principle 2).
"""

import hashlib
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from egolabs.config import get_settings

MiB = 1024 * 1024
S3_MIN_PART = 5 * MiB
S3_MAX_PARTS = 10_000


def _client(endpoint: str, config: Config) -> Any:
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        region_name=settings.s3_region,
        config=config,
    )


@lru_cache
def get_s3_client() -> Any:
    """Short timeouts: health checks and metadata calls."""
    return _client(
        get_settings().s3_endpoint_url,
        Config(signature_version="s3v4", connect_timeout=2, read_timeout=5, retries={"max_attempts": 1}),
    )


@lru_cache
def get_transfer_client() -> Any:
    """Long timeouts and retries: moving file bytes."""
    return _client(
        get_settings().s3_endpoint_url,
        Config(signature_version="s3v4", connect_timeout=5, read_timeout=300, retries={"max_attempts": 5}),
    )


@lru_cache
def get_presign_client() -> Any:
    """Signs URLs for the address browsers use (the signature covers the host)."""
    settings = get_settings()
    return _client(
        settings.s3_public_endpoint_url or settings.s3_endpoint_url,
        Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def required_buckets() -> list[str]:
    settings = get_settings()
    return [settings.s3_bucket_raw, settings.s3_bucket_derived]


def check_buckets() -> None:
    """Raise if any required bucket is missing or storage is unreachable."""
    client = get_s3_client()
    for bucket in required_buckets():
        client.head_bucket(Bucket=bucket)


def ensure_buckets() -> list[str]:
    """Create any missing bucket. Returns the names created."""
    client = get_s3_client()
    created = []
    for bucket in required_buckets():
        try:
            client.head_bucket(Bucket=bucket)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") not in ("404", "NoSuchBucket", "NotFound"):
                raise
            client.create_bucket(Bucket=bucket)
            created.append(bucket)
    return created


# --- multipart uploads (browser → storage) -------------------------------------------------------


def part_size_for(size_bytes: int) -> int:
    """Part size in whole MiB, at least the configured size, and small enough to stay within 10,000 parts."""
    size = max(get_settings().upload_part_size_bytes, S3_MIN_PART)
    needed = -(-size_bytes // S3_MAX_PARTS)  # ceil
    if needed > size:
        size = -(-needed // MiB) * MiB
    return size


def part_count(size_bytes: int, part_size: int) -> int:
    return max(1, -(-size_bytes // part_size))


def create_multipart(bucket: str, key: str, content_type: str | None) -> str:
    extra = {"ContentType": content_type} if content_type else {}
    return get_s3_client().create_multipart_upload(Bucket=bucket, Key=key, **extra)["UploadId"]


def presign_part(bucket: str, key: str, upload_id: str, part_number: int, expires_s: int = 3600) -> str:
    return get_presign_client().generate_presigned_url(
        "upload_part",
        Params={"Bucket": bucket, "Key": key, "UploadId": upload_id, "PartNumber": part_number},
        ExpiresIn=expires_s,
    )


def list_parts(bucket: str, key: str, upload_id: str) -> list[dict[str, Any]]:
    """Parts already stored for a multipart upload, so an interrupted upload can resume."""
    client = get_s3_client()
    parts: list[dict[str, Any]] = []
    marker = 0
    while True:
        res = client.list_parts(Bucket=bucket, Key=key, UploadId=upload_id, PartNumberMarker=marker)
        parts += [
            {
                "part_number": p["PartNumber"],
                "etag": p["ETag"],
                "size": p["Size"],
                "last_modified": p.get("LastModified"),
            }
            for p in res.get("Parts", [])
        ]
        if not res.get("IsTruncated"):
            return parts
        marker = res["NextPartNumberMarker"]


def complete_multipart(bucket: str, key: str, upload_id: str, parts: Iterable[tuple[int, str]]) -> None:
    get_s3_client().complete_multipart_upload(
        Bucket=bucket,
        Key=key,
        UploadId=upload_id,
        MultipartUpload={"Parts": [{"PartNumber": n, "ETag": etag} for n, etag in sorted(parts)]},
    )


def abort_multipart(bucket: str, key: str, upload_id: str) -> None:
    get_s3_client().abort_multipart_upload(Bucket=bucket, Key=key, UploadId=upload_id)


# --- objects ---------------------------------------------------------------------------------------


def object_size(bucket: str, key: str) -> int | None:
    try:
        return int(get_s3_client().head_object(Bucket=bucket, Key=key)["ContentLength"])
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
            return None
        raise


def download_and_hash(bucket: str, key: str, dest: Path, chunk: int = 8 * MiB) -> tuple[str, int]:
    """Stream an object to `dest`, returning (sha256 hex, size) without holding it in memory."""
    body = get_transfer_client().get_object(Bucket=bucket, Key=key)["Body"]
    digest = hashlib.sha256()
    size = 0
    with dest.open("wb") as fh:
        for block in body.iter_chunks(chunk):
            digest.update(block)
            fh.write(block)
            size += len(block)
    return digest.hexdigest(), size


def download(bucket: str, key: str, dest: Path) -> None:
    get_transfer_client().download_file(bucket, key, str(dest))


def upload(path: Path, bucket: str, key: str, content_type: str | None = None) -> None:
    extra = {"ContentType": content_type} if content_type else None
    get_transfer_client().upload_file(str(path), bucket, key, ExtraArgs=extra)


def put_raw(path: Path, key: str, content_type: str | None = None) -> bool:
    """Write a raw object once. Returns False (and writes nothing) if the key already exists."""
    bucket = get_settings().s3_bucket_raw
    if object_size(bucket, key) is not None:
        return False
    upload(path, bucket, key, content_type)
    return True


def put_bytes(data: bytes, bucket: str, key: str, content_type: str | None = None) -> None:
    extra = {"ContentType": content_type} if content_type else {}
    get_s3_client().put_object(Bucket=bucket, Key=key, Body=data, **extra)


def get_bytes(bucket: str, key: str) -> bytes:
    return get_s3_client().get_object(Bucket=bucket, Key=key)["Body"].read()


def list_keys(bucket: str, prefix: str) -> list[str]:
    keys: list[str] = []
    for page in get_s3_client().get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        keys += [obj["Key"] for obj in page.get("Contents", [])]
    return sorted(keys)


def delete(bucket: str, key: str) -> None:
    get_s3_client().delete_object(Bucket=bucket, Key=key)


def presign_get(bucket: str, key: str, expires_s: int = 3600, filename: str | None = None) -> str:
    """A signed GET link; with `filename`, browsers save it under that name instead of playing it."""
    params: dict[str, str] = {"Bucket": bucket, "Key": key}
    if filename:
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in filename)
        params["ResponseContentDisposition"] = f'attachment; filename="{safe}"'
    return get_presign_client().generate_presigned_url("get_object", Params=params, ExpiresIn=expires_s)


def sha256_file(path: Path, chunk: int = 8 * MiB) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(chunk):
            digest.update(block)
    return digest.hexdigest()
