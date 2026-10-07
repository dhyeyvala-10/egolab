"""JSON/CSV metadata sidecars."""

import csv
import io
import json
from pathlib import Path
from typing import Any

MAX_SIDECAR_BYTES = 50 * 1024 * 1024
MAX_CSV_ROWS = 100_000


class SidecarError(Exception):
    pass


def parse(path: Path, fmt: str) -> Any:
    if path.stat().st_size > MAX_SIDECAR_BYTES:
        raise SidecarError(f"sidecar larger than {MAX_SIDECAR_BYTES} bytes")
    text = path.read_bytes().decode("utf-8-sig", errors="strict")
    if fmt == "json":
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise SidecarError(f"invalid JSON: {exc}") from exc
    rows = []
    for i, row in enumerate(csv.DictReader(io.StringIO(text))):
        if i >= MAX_CSV_ROWS:
            raise SidecarError(f"CSV has more than {MAX_CSV_ROWS} rows")
        rows.append(row)
    return rows
