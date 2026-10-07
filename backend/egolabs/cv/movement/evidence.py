"""Evidence frames of an event, stored compactly as runs: [[start, end, step], …] (inclusive)."""


def encode(frames: list[int]) -> list[list[int]]:
    out: list[list[int]] = []
    for f in sorted(set(frames)):
        if out:
            start, end, step = out[-1]
            if start == end and f > end:
                out[-1] = [start, f, f - end]
                continue
            if f - end == step:
                out[-1][1] = f
                continue
        out.append([f, f, 1])
    return out


def decode(runs: list[list[int]]) -> list[int]:
    return [f for start, end, step in runs for f in range(start, end + 1, max(1, step))]


def count(runs: list[list[int]]) -> int:
    return sum((end - start) // max(1, step) + 1 for start, end, step in runs)
