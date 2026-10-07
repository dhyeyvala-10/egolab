"""
A pipeline's graph: `{"nodes": [{"id", "type", "config", "retries"}], "edges": [{"from", "to"}]}`, where
`retries` is how many times the engine retries the step on its own after a transient failure.

Validation checks what the engine relies on: known step types (each at most once), configs that parse,
edges between existing nodes, no cycles, no per-video step after a whole-run step, and every step's hard
requirements upstream. `normalize` fills each config's defaults, so a stored version says exactly what
ran even if a default changes later; `graph_hash` ignores node order.
"""

import hashlib
import json
import re
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from egolabs.pipelines.steps import STEPS

NODE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
MAX_NODES = 40
MAX_RETRIES = 5  # automatic retries of a step after a transient failure


class GraphError(ValueError):
    def __init__(self, errors: list[dict[str, Any]]):
        super().__init__("; ".join(e["message"] for e in errors))
        self.errors = errors


@dataclass
class Graph:
    nodes: dict[str, dict[str, Any]]  # id -> {"id", "type", "config"}
    edges: list[tuple[str, str]]
    parents: dict[str, list[str]] = field(default_factory=dict)
    children: dict[str, list[str]] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)  # topological

    @classmethod
    def load(cls, raw: dict[str, Any]) -> "Graph":
        """A stored (already validated) graph."""
        g = cls(
            {n["id"]: n for n in raw.get("nodes", [])}, [(e["from"], e["to"]) for e in raw.get("edges", [])]
        )
        g._index()
        return g

    def _index(self) -> None:
        self.parents = {n: [] for n in self.nodes}
        self.children = {n: [] for n in self.nodes}
        for a, b in self.edges:
            self.children[a].append(b)
            self.parents[b].append(a)
        indeg = {n: len(p) for n, p in self.parents.items()}
        queue = deque(sorted(n for n, d in indeg.items() if d == 0))
        self.order = []
        while queue:
            n = queue.popleft()
            self.order.append(n)
            for c in sorted(self.children[n]):
                indeg[c] -= 1
                if indeg[c] == 0:
                    queue.append(c)

    def type_of(self, node_id: str) -> str:
        return str(self.nodes[node_id]["type"])

    def per_video(self, node_id: str) -> bool:
        return STEPS[self.type_of(node_id)].per_video

    def ancestors(self, node_id: str) -> list[str]:
        seen: list[str] = []
        stack = list(self.parents[node_id])
        while stack:
            n = stack.pop()
            if n not in seen:
                seen.append(n)
                stack.extend(self.parents[n])
        return seen

    def upstream_of_type(self, node_id: str, step_type: str) -> str | None:
        return next((a for a in self.ancestors(node_id) if self.type_of(a) == step_type), None)

    def roots(self) -> list[str]:
        return [n for n in self.order if not self.parents[n]]


def validate(raw: Any) -> dict[str, Any]:
    """The normalized graph (configs with their defaults), or GraphError listing every problem found."""
    errors: list[dict[str, Any]] = []

    def err(message: str, node: str | None = None) -> None:
        errors.append({"node_id": node, "message": message})

    if (
        not isinstance(raw, dict)
        or not isinstance(raw.get("nodes"), list)
        or not isinstance(raw.get("edges", []), list)
    ):
        raise GraphError([{"node_id": None, "message": "A graph has a list of nodes and a list of edges"}])
    nodes: dict[str, dict[str, Any]] = {}
    types: dict[str, str] = {}
    if not raw["nodes"]:
        err("Add at least one step")
    if len(raw["nodes"]) > MAX_NODES:
        err(f"At most {MAX_NODES} steps")
    for n in raw["nodes"]:
        nid = n.get("id") if isinstance(n, dict) else None
        if not isinstance(nid, str) or not NODE_ID.match(nid):
            err(f"Step id {nid!r} must be 1–64 lowercase letters, digits, - or _")
            continue
        if nid in nodes:
            err(f"Two steps have the id {nid!r}", nid)
            continue
        stype = n.get("type")
        if stype not in STEPS:
            err(f"Unknown step type {stype!r}", nid)
            continue
        if stype in types:
            err(f"{STEPS[stype].label} appears twice (steps {types[stype]!r} and {nid!r}); keep one", nid)
            continue
        types[stype] = nid
        try:
            config = STEPS[stype].config.model_validate(n.get("config") or {})
        except ValidationError as exc:
            for e in exc.errors():
                where = ".".join(str(p) for p in e["loc"]) or "config"
                err(f"{STEPS[stype].label}: {where}: {e['msg']}", nid)
            continue
        problem = STEPS[stype].check(config)
        if problem:
            err(f"{STEPS[stype].label}: {problem}", nid)
        retries = n.get("retries", 0)
        if not isinstance(retries, int) or isinstance(retries, bool) or not 0 <= retries <= MAX_RETRIES:
            err(f"{STEPS[stype].label}: retries must be a whole number from 0 to {MAX_RETRIES}", nid)
            continue
        nodes[nid] = {"id": nid, "type": stype, "config": config.model_dump(mode="json"), "retries": retries}

    edges: list[tuple[str, str]] = []
    for e in raw.get("edges", []):
        a, b = (e.get("from"), e.get("to")) if isinstance(e, dict) else (None, None)
        if a not in nodes or b not in nodes:
            if a in types.values() and b in types.values():
                continue  # an edge touching a step that failed validation: reported there already
            err(f"Edge {a!r} → {b!r} connects a step that doesn't exist")
            continue
        if a == b:
            err("A step can't feed itself", a)
            continue
        if (a, b) in edges:
            continue
        edges.append((a, b))

    graph = Graph(nodes, edges)
    graph._index()
    if len(graph.order) < len(nodes):
        stuck = sorted(set(nodes) - set(graph.order))
        err(f"The steps form a loop ({', '.join(stuck)}); a pipeline must flow one way")
    else:
        for a, b in edges:
            if not graph.per_video(a) and graph.per_video(b):
                err(f"{STEPS[graph.type_of(b)].label} runs per video, so it can't come after "
                    f"{STEPS[graph.type_of(a)].label}, which runs once for the whole run", b)  # fmt: skip
        for nid in graph.order:
            step = STEPS[graph.type_of(nid)]
            for needed in step.requires:
                if graph.upstream_of_type(nid, needed) is None:
                    err(f"{step.label} needs {STEPS[needed].label} before it", nid)
    if errors:
        raise GraphError(errors)
    return {
        "nodes": [nodes[n] for n in graph.order],
        "edges": [{"from": a, "to": b} for a, b in sorted(edges)],
    }


def graph_hash(graph: dict[str, Any]) -> str:
    canonical = {
        "nodes": sorted(graph["nodes"], key=lambda n: n["id"]),
        "edges": sorted(graph["edges"], key=lambda e: (e["from"], e["to"])),
    }
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def auto_layout(graph: dict[str, Any], dx: int = 230, dy: int = 96) -> dict[str, dict[str, int]]:
    """Positions for the builder: a column per step of depth (longest path from a first step), rows in order."""
    g = Graph.load(graph)
    depth: dict[str, int] = {}
    for n in g.order:
        depth[n] = max((depth[p] + 1 for p in g.parents[n]), default=0)
    rows: dict[int, int] = {}
    out = {}
    keys = list(STEPS)
    for n in sorted(g.order, key=lambda n: (depth[n], keys.index(g.type_of(n)))):
        r = rows.get(depth[n], 0)
        rows[depth[n]] = r + 1
        out[n] = {"x": 24 + depth[n] * dx, "y": 24 + r * dy}
    return out
