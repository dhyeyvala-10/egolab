/**
 * Pipelines in the browser (spec Phase 7): the graph shape the API stores, where the builder draws each
 * node, and how steps and runs are summarised.
 */
import type { RunSummary, StepStatus, StepTypeRead } from "@/lib/api/types";

export interface GraphNode {
  id: string;
  type: string;
  config: Record<string, unknown>;
  retries: number;
}
export interface GraphEdge {
  from: string;
  to: string;
}
export interface PipelineGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}
export type Layout = Record<string, { x: number; y: number }>;

export const NODE_W = 196;
export const NODE_H = 64;
const DX = 230;
const DY = 96;

export function asGraph(raw: unknown): PipelineGraph {
  const g = (raw ?? {}) as Partial<PipelineGraph>;
  return {
    nodes: (g.nodes ?? []).map((n) => ({ id: n.id, type: n.type, config: n.config ?? {}, retries: n.retries ?? 0 })),
    edges: (g.edges ?? []).map((e) => ({ from: e.from, to: e.to })),
  };
}

/** Columns by depth (longest path from a first step), rows in step order: the same as the API's layout. */
export function autoLayout(graph: PipelineGraph, order: string[] = []): Layout {
  const parents = new Map(graph.nodes.map((n) => [n.id, [] as string[]]));
  for (const e of graph.edges) parents.get(e.to)?.push(e.from);
  const depth = new Map<string, number>();
  const visit = (id: string, seen: Set<string>): number => {
    if (depth.has(id)) return depth.get(id)!;
    if (seen.has(id)) return 0; // a loop: validation reports it
    seen.add(id);
    const d = Math.max(-1, ...(parents.get(id) ?? []).map((p) => visit(p, seen))) + 1;
    depth.set(id, d);
    return d;
  };
  graph.nodes.forEach((n) => visit(n.id, new Set()));
  const rank = (t: string) => (order.indexOf(t) < 0 ? order.length : order.indexOf(t));
  const rows = new Map<number, number>();
  const out: Layout = {};
  [...graph.nodes]
    .sort((a, b) => depth.get(a.id)! - depth.get(b.id)! || rank(a.type) - rank(b.type))
    .forEach((n) => {
      const d = depth.get(n.id)!;
      const r = rows.get(d) ?? 0;
      rows.set(d, r + 1);
      out[n.id] = { x: 24 + d * DX, y: 24 + r * DY };
    });
  return out;
}

/** A layout with a position for every node (new nodes go below the rest). */
export function completeLayout(graph: PipelineGraph, layout: Layout, order: string[] = []): Layout {
  const missing = graph.nodes.filter((n) => !layout[n.id]);
  if (!missing.length) return layout;
  if (missing.length === graph.nodes.length) return autoLayout(graph, order);
  const bottom = Math.max(...Object.values(layout).map((p) => p.y)) + DY;
  const out = { ...layout };
  missing.forEach((n, i) => (out[n.id] = { x: 24 + i * DX, y: bottom }));
  return out;
}

export function uniqueId(type: string, taken: Set<string>): string {
  const base = type.replace(/^quality_/, "").replace(/_/g, "-").slice(0, 40);
  if (!taken.has(base)) return base;
  for (let i = 2; ; i++) if (!taken.has(`${base}-${i}`)) return `${base}-${i}`;
}

/** Step statuses as badge tones (see components/ui/StatusBadge). */
export const STEP_TONE: Record<StepStatus, string> = {
  pending: "queued",
  queued: "queued",
  running: "running",
  retry_wait: "retrying",
  succeeded: "succeeded",
  failed: "failed",
  skipped: "cancelled",
  cancelled: "cancelled",
};

export const STEP_LABEL: Record<StepStatus, string> = {
  pending: "Waiting",
  queued: "Queued",
  running: "Running",
  retry_wait: "Retry scheduled",
  succeeded: "Succeeded",
  failed: "Failed",
  skipped: "Skipped",
  cancelled: "Cancelled",
};

/** Order the progress bar stacks step statuses in. */
export const PROGRESS_ORDER: StepStatus[] = ["succeeded", "skipped", "running", "queued", "retry_wait", "failed", "pending", "cancelled"];

/** How one node (or a run) is doing overall, from its step counts. */
export function overall(counts: Record<string, number>): StepStatus | "empty" {
  const n = (s: StepStatus) => counts[s] ?? 0;
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  if (!total) return "empty";
  if (n("failed")) return "failed";
  if (n("running")) return "running";
  if (n("retry_wait")) return "retry_wait";
  if (n("queued")) return "queued";
  if (n("pending")) return "pending";
  if (n("succeeded")) return "succeeded";
  if (n("cancelled")) return "cancelled";
  return "skipped";
}

export function stepCount(counts: Record<string, number>): { done: number; total: number } {
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  const done = (counts.succeeded ?? 0) + (counts.skipped ?? 0);
  return { done, total };
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`;
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)} s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  if (m < 60) return `${m} min ${s} s`;
  return `${Math.floor(m / 60)} h ${m % 60} min`;
}

export function runName(r: Pick<RunSummary, "pipeline" | "number">): string {
  return `${r.pipeline.name} #${r.number}`;
}

export const CATEGORY_ORDER = ["Ingest", "Tracking", "Movement", "Quality", "Output", "Dataset"];

export function byCategory(steps: StepTypeRead[]): [string, StepTypeRead[]][] {
  const groups = new Map<string, StepTypeRead[]>();
  for (const s of steps) groups.set(s.category, [...(groups.get(s.category) ?? []), s]);
  return [...groups.entries()].sort(([a], [b]) => CATEGORY_ORDER.indexOf(a) - CATEGORY_ORDER.indexOf(b));
}

/** Where a step's result points: the record it made, for a link from the run page. */
export function resultLinks(stepType: string, result: Record<string, unknown>): { label: string; href: string }[] {
  const s = (k: string) => (typeof result[k] === "string" ? (result[k] as string) : null);
  const links: { label: string; href: string }[] = [];
  const cv = s("cv_run_id");
  if (cv && stepType === "hand_tracking") links.push({ label: "Hand run", href: `/cv/hands/${cv}` });
  if (cv && stepType === "object_detection") links.push({ label: "Object run", href: `/cv/objects/${cv}` });
  if (cv && stepType === "movement") links.push({ label: "Events", href: `/cv/movements/runs/${cv}` });
  const hand = s("hand_run_id");
  if (hand && stepType === "finger_tracking") links.push({ label: "Fingers", href: `/cv/fingers/${hand}` });
  const version = s("dataset_version_id");
  if (version) links.push({ label: stepType === "export" ? "Version" : `v${String(result.number ?? "")}`.trim(), href: `/datasets/versions/${version}` });
  return links;
}
