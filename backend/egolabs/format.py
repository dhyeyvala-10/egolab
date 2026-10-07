"""Sizes and durations as people read them, for messages."""


def human_bytes(n: float) -> str:
    """Decimal units, as the web app shows them (1 GB = 1000³ bytes)."""
    units = ("B", "KB", "MB", "GB", "TB")
    i = 0
    while n >= 1000 and i < len(units) - 1:
        n, i = n / 1000, i + 1
    return f"{n:.0f} {units[i]}" if i == 0 or n >= 100 else f"{n:.1f} {units[i]}"


def human_duration(seconds: float) -> str:
    s = round(seconds)
    h, rest = divmod(s, 3600)
    m, sec = divmod(rest, 60)
    if h:
        return f"{h} h {m} min" if m else f"{h} h"
    if m:
        return f"{m} min {sec} s" if sec else f"{m} min"
    return f"{sec} s"
