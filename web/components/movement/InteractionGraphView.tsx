"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import type { InteractionGraph } from "@/lib/api/types";
import { GRAPH_COLUMNS, layoutGraph, pathsThrough } from "@/lib/cv/graph";
import { cn } from "@/lib/cn";

const HEADERS = ["Hand", "Finger(s)", "Movement", "Object", "Time range"];
const COL_W = 150;
const NODE_W = 118;
const GAP = 42;
const TIME_W = 320;

/**
 * Hand → Finger(s) → Movement → Object → Time range. Links are as wide as the number of events that take
 * them; the time range column puts each event's span on its object's row. Hover or focus a node to follow
 * its chains; click an event span to open it.
 */
export function InteractionGraphView({ graph, duration }: { graph: InteractionGraph; duration: number }) {
  const router = useRouter();
  const [hover, setHover] = useState<string | null>(null);
  const [table, setTable] = useState(false);
  const layout = useMemo(() => layoutGraph(graph), [graph]);
  const lit = useMemo(() => pathsThrough(graph, hover), [graph, hover]);
  const width = GRAPH_COLUMNS.length * COL_W + GAP + TIME_W;
  const x = (col: number) => col * COL_W;
  const tx = (t: number) => GRAPH_COLUMNS.length * COL_W + GAP + (Math.min(duration, Math.max(0, t)) / Math.max(duration, 1e-6)) * (TIME_W - 8);

  if (!graph.total_events) return <p className="py-2 text-xs text-ink-3">No events to connect for this video yet.</p>;
  return (
    <div className="flex flex-col gap-2" data-testid="interaction-graph">
      <div className="flex items-center justify-between gap-2 text-xs text-ink-3">
        <span>
          {graph.total_events} event{graph.total_events === 1 ? "" : "s"} · link width = events
          {graph.events.length < graph.total_events ? ` · time range shows the first ${graph.events.length}` : ""}
        </span>
        <label className="flex items-center gap-1.5 text-ink-2">
          <input type="checkbox" checked={table} onChange={(e) => setTable(e.target.checked)} /> Table view
        </label>
      </div>
      {table ? (
        <div className="max-h-96 overflow-auto rounded-md border border-line">
          <table className="w-full border-collapse text-xs">
            <thead className="sticky top-0 bg-subtle">
              <tr>{HEADERS.map((h) => <th key={h} className="px-2 py-1.5 text-left font-semibold text-ink-3">{h}</th>)}</tr>
            </thead>
            <tbody>
              {graph.events.map((e) => {
                const labels = e.path.map((id) => layout.byId.get(id)?.label ?? id);
                return (
                  <tr key={e.id} className="cursor-pointer border-t border-line hover:bg-hover" onClick={() => router.push(`/cv/movements/events/${e.id}`)}>
                    <td className="px-2 py-1">{labels[0]}</td>
                    <td className="px-2 py-1">{labels.slice(1, -2).join(", ")}</td>
                    <td className="px-2 py-1 font-medium">{labels.at(-2)}</td>
                    <td className="px-2 py-1">{labels.at(-1)}</td>
                    <td className="px-2 py-1 font-mono tabular-nums">{e.start_s.toFixed(2)}–{e.end_s.toFixed(2)} s</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <svg viewBox={`0 -22 ${width} ${layout.height + 22}`} width={width} height={layout.height + 22} role="img"
               aria-label={`Interaction graph of ${graph.total_events} events`} className="block">
            {HEADERS.map((h, i) => (
              <text key={h} x={i < 4 ? x(i) : tx(0)} y={-8} className="fill-ink-3 text-[11px] font-semibold">{h}</text>
            ))}
            {layout.links.map((l) => {
              const a = layout.byId.get(l.source);
              const b = layout.byId.get(l.target);
              if (!a || !b) return null;
              const x0 = x(a.column) + NODE_W;
              const x1 = x(b.column);
              const on = hover ? lit.nodes.has(a.id) && lit.nodes.has(b.id) : false;
              return (
                <path key={`${l.source}>${l.target}`} d={`M${x0},${a.y} C${(x0 + x1) / 2},${a.y} ${(x0 + x1) / 2},${b.y} ${x1},${b.y}`}
                      fill="none" stroke="var(--color-ai)" strokeWidth={l.width} strokeOpacity={hover ? (on ? 0.75 : 0.08) : 0.3}>
                  <title>{`${a.label} → ${b.label}: ${l.count} event${l.count === 1 ? "" : "s"}`}</title>
                </path>
              );
            })}
            {/* Time range: each event's span on its object's row. */}
            <line x1={tx(0)} x2={tx(duration)} y1={layout.height - 4} y2={layout.height - 4} stroke="var(--color-line)" />
            <text x={tx(0)} y={layout.height + 10} className="fill-ink-3 font-mono text-[10px]">0 s</text>
            <text x={tx(duration)} y={layout.height + 10} textAnchor="end" className="fill-ink-3 font-mono text-[10px]">{duration.toFixed(1)} s</text>
            {graph.events.map((e) => {
              const obj = layout.byId.get(e.path.at(-1) ?? "");
              if (!obj) return null;
              const on = !hover || lit.events.has(e.id);
              const x0 = tx(e.start_s);
              return (
                <rect key={e.id} x={x0} y={obj.y - 5} width={Math.max(3, tx(e.end_s) - x0)} height={10} rx={2}
                      fill="var(--color-ai)" fillOpacity={on ? 0.85 : 0.15} stroke="var(--color-canvas)" strokeWidth={1}
                      className="cursor-pointer" onClick={() => router.push(`/cv/movements/events/${e.id}`)} data-event={e.id}>
                  <title>{`${e.label}: ${e.start_s.toFixed(2)}–${e.end_s.toFixed(2)} s`}</title>
                </rect>
              );
            })}
            {layout.nodes.map((n) => {
              const on = hover ? lit.nodes.has(n.id) : true;
              return (
                <g key={n.id} tabIndex={0} role="button" aria-label={`${n.label}: ${n.count} events`} data-node={n.id}
                   onMouseEnter={() => setHover(n.id)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(n.id)} onBlur={() => setHover(null)}
                   className="cursor-default outline-none" opacity={on ? 1 : 0.35}>
                  <rect x={x(n.column)} y={n.y - 11} width={NODE_W} height={22} rx={4}
                        className={cn("fill-canvas", hover === n.id ? "stroke-ink" : "stroke-line-strong")} strokeWidth={1} />
                  <text x={x(n.column) + 7} y={n.y + 4} className="fill-ink text-[11.5px] font-medium">
                    {n.label.length > 13 ? `${n.label.slice(0, 12)}…` : n.label}
                  </text>
                  <text x={x(n.column) + NODE_W - 7} y={n.y + 4} textAnchor="end" className="fill-ink-3 font-mono text-[10.5px] tabular-nums">{n.count}</text>
                </g>
              );
            })}
          </svg>
        </div>
      )}
    </div>
  );
}
