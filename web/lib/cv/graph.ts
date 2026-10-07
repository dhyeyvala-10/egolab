import type { InteractionGraph } from "@/lib/api/types";

export const GRAPH_COLUMNS = ["hand", "finger", "movement", "object"] as const;
export type GraphKind = (typeof GRAPH_COLUMNS)[number];

export interface PlacedNode {
  id: string;
  kind: GraphKind;
  label: string;
  count: number;
  column: number;
  y: number; // centre, px
}

export interface PlacedLink {
  source: string;
  target: string;
  count: number;
  width: number;
}

export interface GraphLayout {
  nodes: PlacedNode[];
  byId: Map<string, PlacedNode>;
  links: PlacedLink[];
  height: number;
  rowHeight: number;
}

const ROW = 30;
const PAD = 12;

/** Place nodes in their column (in the API's order: biggest first), and size links by how many events use them. */
export function layoutGraph(graph: InteractionGraph): GraphLayout {
  const columns = GRAPH_COLUMNS.map((kind) => graph.nodes.filter((n) => n.kind === kind));
  const rows = Math.max(1, ...columns.map((c) => c.length));
  const height = rows * ROW + PAD * 2;
  const nodes: PlacedNode[] = [];
  columns.forEach((col, ci) => {
    const top = PAD + ((rows - col.length) * ROW) / 2; // centre shorter columns
    col.forEach((n, i) => nodes.push({ ...n, kind: n.kind as GraphKind, column: ci, y: top + i * ROW + ROW / 2 }));
  });
  const max = Math.max(1, ...graph.links.map((l) => l.count));
  const links = graph.links.map((l) => ({ ...l, width: 1.5 + (8.5 * l.count) / max }));
  return { nodes, byId: new Map(nodes.map((n) => [n.id, n])), links, height, rowHeight: ROW };
}

/** Node ids on any event path through `nodeId` (so hovering a node lights its whole chains). */
export function pathsThrough(graph: InteractionGraph, nodeId: string | null): { nodes: Set<string>; events: Set<string> } {
  const nodes = new Set<string>();
  const events = new Set<string>();
  if (!nodeId) return { nodes, events };
  for (const e of graph.events) {
    if (!e.path.includes(nodeId)) continue;
    events.add(e.id);
    for (const id of e.path) nodes.add(id);
  }
  return { nodes, events };
}
