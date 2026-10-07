"""
Built-in templates: starting points for a pipeline. Using one copies its graph into a new pipeline; they are
configuration shipped with the code (like the built-in movement classes), not data.
"""

from typing import Any

from egolabs.pipelines.graph import auto_layout, validate


def _n(nid: str, type_: str, config: dict[str, Any] | None = None, retries: int = 0) -> dict[str, Any]:
    return {"id": nid, "type": type_, "config": config or {}, "retries": retries}


def _e(*pairs: str) -> list[dict[str, str]]:
    out = []
    for p in pairs:
        a, b = p.split(">")
        out.append({"from": a, "to": b})
    return out


_PROCESS_NODES = [
    _n("ingest", "ingest"), _n("frames", "extract_frames"), _n("hands", "hand_tracking", retries=1),
    _n("fingers", "finger_tracking"), _n("objects", "object_detection", retries=1), _n("movement", "movement"),
    _n("render", "render_video"),
]  # fmt: skip
_PROCESS_EDGES = _e("ingest>frames", "frames>hands", "frames>objects", "hands>fingers", "hands>movement",
                    "objects>movement", "movement>render")  # fmt: skip
_QUALITY_NODES = [
    _n("blur", "quality_blur"),
    _n("light", "quality_low_light"),
    _n("occlusion", "quality_occlusion"),
    _n("duplicates", "quality_duplicates"),
]
_QUALITY_EDGES = _e("frames>blur", "frames>light", "hands>occlusion", "frames>duplicates")

RAW: list[dict[str, Any]] = [
    {
        "key": "process-videos",
        "name": "Process videos",
        "description": "Every video from raw file to annotated video: ingest check, frames, hands and fingers, "
        "objects, movements, quality checks, and a rendered video with everything drawn on.",
        "graph": {"nodes": _PROCESS_NODES + _QUALITY_NODES, "edges": _PROCESS_EDGES + _QUALITY_EDGES},
    },
    {
        "key": "end-to-end",
        "name": "Process, build a dataset, export",
        "description": "Process videos as above, leave out blurry and dark ones, build a new dataset version from "
        "the rest, and export it (Ego Labs native and COCO).",
        "graph": {
            "nodes": _PROCESS_NODES
            + _QUALITY_NODES
            + [
                _n(
                    "dataset",
                    "dataset_build",
                    {
                        "dataset": "Pipeline dataset",
                        "statuses": ["auto_detected", "needs_review", "confirmed"],
                        "exclude_quality_flags": ["blurry", "low_light", "corrupt"],
                    },
                ),
                _n("export", "export", {"formats": ["egolabs", "coco"]}),
            ],
            "edges": _PROCESS_EDGES
            + _QUALITY_EDGES
            + _e("movement>dataset", "blur>dataset", "light>dataset", "dataset>export"),
        },  # fmt: skip
    },
    {
        "key": "quality-audit",
        "name": "Quality audit",
        "description": "Blur, low light, occlusion, and near-duplicate checks; each sets a flag the dataset builder "
        "can leave out.",
        "graph": {
            "nodes": [
                _n("ingest", "ingest"),
                _n("frames", "extract_frames"),
                _n("hands", "hand_tracking", {"reuse": True}),
                *_QUALITY_NODES,
            ],
            "edges": _e("ingest>frames", "frames>hands") + _QUALITY_EDGES,
        },  # fmt: skip
    },
    {
        "key": "reclassify",
        "name": "Re-classify movements",
        "description": "Classify movements again from each video's latest hand and object runs (for a new "
        "classifier config), and render the annotated video.",
        "graph": {
            "nodes": [_n("movement", "movement"), _n("render", "render_video")],
            "edges": _e("movement>render"),
        },
    },
    {
        "key": "tracking-only",
        "name": "Tracking only",
        "description": "Hands, fingers, and objects, without classification.",
        "graph": {
            "nodes": [
                _n("ingest", "ingest"),
                _n("frames", "extract_frames"),
                _n("hands", "hand_tracking", retries=1),
                _n("fingers", "finger_tracking"),
                _n("objects", "object_detection", retries=1),
            ],
            "edges": _e("ingest>frames", "frames>hands", "frames>objects", "hands>fingers"),
        },  # fmt: skip
    },
]


def templates() -> list[dict[str, Any]]:
    out = []
    for t in RAW:
        graph = validate(t["graph"])
        out.append({**t, "graph": graph, "layout": auto_layout(graph)})
    return out


def get(key: str) -> dict[str, Any] | None:
    return next((t for t in templates() if t["key"] == key), None)
