"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import type { LineageGraph, LineageNode } from "@/lib/api/types";
import { cn } from "@/lib/cn";

const TYPE_LABEL: Record<string, string> = {
  sample: "Sample", dataset_version: "Dataset version", dataset: "Dataset", annotation: "Annotation", event: "Movement event",
  cv_run: "Model run", model_version: "Model version", job: "Job", video: "Video", upload: "Upload", raw_file: "Raw file",
  frames: "Frames", session: "Session",
};
const W = 196, H = 54, GX = 56, GY = 12, PAD = 8;

/** Columns by distance from the sample (shortest path), rows in a stable order within each column. */
export function layout(graph: LineageGraph) {
  const depth = new Map<string, number>([[graph.root, 0]]);
  const queue = [graph.root];
  while (queue.length) {
    const id = queue.shift()!;
    for (const e of graph.edges) if (e.source === id && !depth.has(e.target)) { depth.set(e.target, depth.get(id)! + 1); queue.push(e.target); }
  }
  for (const n of graph.nodes) if (!depth.has(n.id)) depth.set(n.id, 0);
  const order = Object.keys(TYPE_LABEL);
  const cols = new Map<number, LineageNode[]>();
  for (const n of graph.nodes) {
    const d = depth.get(n.id)!;
    cols.set(d, [...(cols.get(d) ?? []), n]);
  }
  const pos = new Map<string, { x: number; y: number }>();
  let height = 0;
  for (const [d, list] of cols) {
    list.sort((a, b) => order.indexOf(a.type) - order.indexOf(b.type) || a.label.localeCompare(b.label));
    list.forEach((n, i) => pos.set(n.id, { x: PAD + d * (W + GX), y: PAD + i * (H + GY) }));
    height = Math.max(height, PAD * 2 + list.length * (H + GY));
  }
  const width = PAD * 2 + Math.max(...cols.keys(), 0) * (W + GX) + W;
  return { pos, width, height, depth };
}

// Which way to follow first when tracing to the raw file: through the model chain, not a shortcut.
const PREFER = ["event", "annotation", "cv_run", "video", "upload", "raw_file", "session", "frames", "model_version", "job", "dataset_version", "dataset"];

/**
 * The chain from the sample to its raw file, following the processing that produced it first (event →
 * model runs → video → raw file) rather than the shortest hop.
 */
export function pathToRaw(graph: LineageGraph): string[] {
  const type = new Map(graph.nodes.map((n) => [n.id, n.type]));
  const rank = (id: string) => { const i = PREFER.indexOf(type.get(id) ?? ""); return i < 0 ? PREFER.length : i; };
  const seen = new Set<string>();
  const walk = (id: string): string[] | null => {
    if (type.get(id) === "raw_file") return [id];
    seen.add(id);
    const next = graph.edges.filter((e) => e.source === id && !seen.has(e.target)).map((e) => e.target).sort((a, b) => rank(a) - rank(b));
    for (const t of next) {
      const rest = walk(t);
      if (rest) return [id, ...rest];
    }
    return null;
  };
  return walk(graph.root) ?? [];
}

function value(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

/**
 * A sample's lineage as a graph: the sample on the left, then what it came from, column by column, to the raw
 * file. The path to the raw file is drawn darker; click a node to see what it records.
 */
export function LineageView({ graph }: { graph: LineageGraph }) {
  const { pos, width, height } = useMemo(() => layout(graph), [graph]);
  const path = useMemo(() => pathToRaw(graph), [graph]);
  const onPath = useMemo(() => new Set(path.slice(1).map((t, i) => `${path[i]}>${t}`)), [path]);
  const [selected, setSelected] = useState<string>(path.at(-1) ?? graph.root);
  const byId = useMemo(() => new Map(graph.nodes.map((n) => [n.id, n])), [graph]);
  const sel = byId.get(selected);

  return (
    <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
      <div className="flex min-w-0 flex-col gap-3">
        <div className={cn("rounded-md border px-3 py-2 text-xs", graph.reaches_raw_file ? "border-success-line bg-success-bg text-success" : "border-error-line bg-error-bg text-error")} data-testid="reaches">
          {graph.reaches_raw_file ? "✓ Traced to the raw file" : "✗ No path to a raw file"} · {graph.nodes.length} records, {graph.edges.length} links
        </div>
        <div className="overflow-auto rounded-lg border border-line bg-subtle" style={{ maxHeight: 640 }}>
          <svg width={width} height={height} role="img" aria-label="Lineage graph" data-testid="lineage-graph">
            {graph.edges.map((e, i) => {
              const a = pos.get(e.source), b = pos.get(e.target);
              if (!a || !b) return null;
              const strong = onPath.has(`${e.source}>${e.target}`);
              const x1 = a.x + W, y1 = a.y + H / 2, x2 = b.x, y2 = b.y + H / 2;
              const d = b.x > a.x ? `M${x1},${y1} C${x1 + GX / 2},${y1} ${x2 - GX / 2},${y2} ${x2},${y2}`
                : `M${x1},${y1} C${x1 + GX},${y1} ${b.x + W + GX},${y2} ${b.x + W},${y2}`;
              return <path key={i} d={d} fill="none" className={strong ? "stroke-ink" : "stroke-line-strong"} strokeWidth={strong ? 2 : 1}><title>{e.relation.replace(/_/g, " ")}</title></path>;
            })}
            {graph.nodes.map((n) => {
              const p = pos.get(n.id)!;
              const on = n.id === selected;
              return (
                <g key={n.id} transform={`translate(${p.x},${p.y})`} role="button" tabIndex={0} aria-pressed={on} aria-label={`${TYPE_LABEL[n.type] ?? n.type}: ${n.label}`}
                   onClick={() => setSelected(n.id)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setSelected(n.id); } }}
                   className="cursor-pointer" data-node={n.type}>
                  <rect width={W} height={H} rx={6} className={cn("fill-canvas", on ? "stroke-ink" : path.includes(n.id) ? "stroke-ink-2" : "stroke-line-strong")} strokeWidth={on ? 2 : 1} />
                  <text x={10} y={18} className="fill-ink-3 text-[10px] font-semibold uppercase tracking-wider">{TYPE_LABEL[n.type] ?? n.type}</text>
                  <text x={10} y={37} className="fill-ink text-[12px] font-medium">{n.label.length > 26 ? `${n.label.slice(0, 25)}…` : n.label}</text>
                </g>
              );
            })}
          </svg>
        </div>
        <ol className="flex flex-wrap items-center gap-1.5 text-xs" aria-label="Path to the raw file" data-testid="path">
          {path.map((id, i) => {
            const n = byId.get(id)!;
            return (
              <li key={id} className="flex min-w-0 max-w-full items-center gap-1.5">
                {i ? <span aria-hidden className="text-ink-3">→</span> : null}
                <button type="button" onClick={() => setSelected(id)} className={cn("min-w-0 break-all rounded-md border px-2 py-0.5 text-left", id === selected ? "border-ink font-semibold" : "border-line bg-canvas hover:bg-hover")}>
                  {TYPE_LABEL[n.type] ?? n.type}: {n.label}
                </button>
              </li>
            );
          })}
        </ol>
      </div>
      <aside className="flex min-w-0 flex-col gap-2 rounded-lg border border-line bg-canvas p-3 text-xs" aria-label="Selected record" data-testid="node-detail">
        {sel ? (
          <>
            <div className="text-[11px] font-semibold uppercase tracking-wider text-ink-3">{TYPE_LABEL[sel.type] ?? sel.type}</div>
            <div className="break-all text-[13px] font-semibold">{sel.label}</div>
            <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1">
              {Object.entries(sel.detail ?? {}).map(([k, v]) => (
                <div key={k} className="contents"><dt className="text-ink-3">{k.replace(/_/g, " ")}</dt><dd className="break-all font-mono text-[11px]">{value(v)}</dd></div>
              ))}
              <div className="contents"><dt className="text-ink-3">id</dt><dd className="break-all font-mono text-[11px]">{sel.id.split(":").slice(1).join(":")}</dd></div>
            </dl>
            {sel.href ? <Link href={sel.href} className="mt-1 font-semibold underline">Open</Link> : null}
            <div className="mt-2 border-t border-line pt-2 text-ink-2">
              <div className="mb-1 font-semibold text-ink">Links</div>
              <ul className="flex flex-col gap-0.5">
                {graph.edges.filter((e) => e.source === sel.id || e.target === sel.id).map((e, i) => {
                  const other = byId.get(e.source === sel.id ? e.target : e.source);
                  return <li key={i}>{e.source === sel.id ? "→" : "←"} {e.relation.replace(/_/g, " ")} <button type="button" className="underline" onClick={() => other && setSelected(other.id)}>{other?.label}</button></li>;
                })}
              </ul>
            </div>
          </>
        ) : null}
      </aside>
    </div>
  );
}
