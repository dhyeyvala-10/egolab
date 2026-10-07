"use client";

import { useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { cn } from "@/lib/cn";
import { NODE_H, NODE_W, type Layout, type PipelineGraph } from "@/lib/pipelines";

export interface NodeInfo {
  label: string;
  category: string;
  perVideo: boolean;
}

export interface NodeStatus {
  tone: "success" | "error" | "running" | "warning" | "neutral";
  text: string;
}

const TONE_BORDER: Record<NodeStatus["tone"], string> = {
  success: "border-success-line bg-success-bg",
  error: "border-error-line bg-error-bg",
  running: "border-running-line bg-running-bg",
  warning: "border-warning-line bg-warning-bg",
  neutral: "border-line-strong bg-canvas",
};
const TONE_TEXT: Record<NodeStatus["tone"], string> = {
  success: "text-success",
  error: "text-error",
  running: "text-running",
  warning: "text-warning",
  neutral: "text-ink-3",
};

export function edgeKey(from: string, to: string) {
  return `${from}>${to}`;
}

function curve(x1: number, y1: number, x2: number, y2: number) {
  const dx = Math.max(40, Math.abs(x2 - x1) / 2);
  return `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`;
}

/**
 * A pipeline's graph: steps as cards, edges as curves from a step's right side to the next step's left.
 * Editable: drag a card to move it, drag from its ● handle onto another card to connect them, click an
 * edge to select it. Read-only (a run): each card shows how its steps are doing.
 */
export function Canvas({
  graph,
  layout,
  info,
  selected = null,
  selectedEdge = null,
  onSelect,
  onSelectEdge,
  onMove,
  onConnect,
  errors = {},
  status,
  editable = false,
  scale = 1,
  className,
  label = "Pipeline graph",
}: {
  graph: PipelineGraph;
  layout: Layout;
  info: Record<string, NodeInfo>;
  selected?: string | null;
  selectedEdge?: string | null;
  onSelect?: (id: string | null) => void;
  onSelectEdge?: (key: string | null) => void;
  onMove?: (id: string, x: number, y: number) => void;
  onConnect?: (from: string, to: string) => void;
  errors?: Record<string, string[]>;
  status?: Record<string, NodeStatus>;
  editable?: boolean;
  scale?: number;
  className?: string;
  label?: string;
}) {
  const area = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<{ id: string; dx: number; dy: number } | null>(null);
  const [link, setLink] = useState<{ from: string; x: number; y: number } | null>(null);

  const pos = (id: string) => layout[id] ?? { x: 24, y: 24 };
  const width = Math.max(420, ...graph.nodes.map((n) => pos(n.id).x + NODE_W + 40));
  const height = Math.max(160, ...graph.nodes.map((n) => pos(n.id).y + NODE_H + 40));

  const point = (e: { clientX: number; clientY: number }) => {
    const r = area.current!.getBoundingClientRect();
    return { x: (e.clientX - r.left) / scale, y: (e.clientY - r.top) / scale };
  };

  const startDrag = (e: ReactPointerEvent, id: string) => {
    if (!editable || e.button !== 0) return;
    const p = point(e);
    setDrag({ id, dx: p.x - pos(id).x, dy: p.y - pos(id).y });
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  };
  const startLink = (e: ReactPointerEvent, id: string) => {
    e.stopPropagation();
    if (!editable) return;
    const p = point(e);
    setLink({ from: id, x: p.x, y: p.y });
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  };
  const move = (e: ReactPointerEvent) => {
    if (drag) {
      const p = point(e);
      const snap = (v: number) => Math.max(8, Math.round(v / 8) * 8);
      onMove?.(drag.id, snap(p.x - drag.dx), snap(p.y - drag.dy));
    } else if (link) {
      setLink({ ...link, ...point(e) });
    }
  };
  const end = (e: ReactPointerEvent) => {
    if (link) {
      const target = document.elementFromPoint(e.clientX, e.clientY)?.closest("[data-node]")?.getAttribute("data-node");
      if (target && target !== link.from) onConnect?.(link.from, target);
    }
    setDrag(null);
    setLink(null);
  };

  return (
    <div className={cn("overflow-auto rounded-lg border border-line bg-subtle", className)}>
      <div
        ref={area}
        role="group"
        aria-label={label}
        className="relative"
        style={{ width: width * scale, height: height * scale }}
        onPointerMove={move}
        onPointerUp={end}
        onPointerCancel={end}
        onClick={(e) => {
          if (e.target === e.currentTarget) {
            onSelect?.(null);
            onSelectEdge?.(null);
          }
        }}
      >
        <svg width={width * scale} height={height * scale} className="pointer-events-none absolute inset-0" aria-hidden>
          <g transform={`scale(${scale})`}>
            {graph.edges.map((e) => {
              const a = pos(e.from), b = pos(e.to);
              const key = edgeKey(e.from, e.to);
              const on = key === selectedEdge;
              const d = curve(a.x + NODE_W, a.y + NODE_H / 2, b.x, b.y + NODE_H / 2);
              return (
                <g key={key}>
                  <path d={d} fill="none" className={on ? "stroke-accent" : "stroke-line-strong"} strokeWidth={on ? 2.5 : 1.5} />
                  {editable ? (
                    <path d={d} fill="none" stroke="transparent" strokeWidth={14} className="pointer-events-auto cursor-pointer"
                          data-edge={key} onClick={(ev) => { ev.stopPropagation(); onSelectEdge?.(key); onSelect?.(null); }} />
                  ) : null}
                  <circle cx={b.x} cy={b.y + NODE_H / 2} r={3} className={on ? "fill-accent" : "fill-line-strong"} />
                </g>
              );
            })}
            {link ? (
              <path d={curve(pos(link.from).x + NODE_W, pos(link.from).y + NODE_H / 2, link.x, link.y)} fill="none"
                    className="stroke-accent" strokeWidth={2} strokeDasharray="5 4" />
            ) : null}
          </g>
        </svg>
        {graph.nodes.map((n) => {
          const p = pos(n.id);
          const meta = info[n.type];
          const st = status?.[n.id];
          const bad = Boolean(errors[n.id]?.length);
          const on = selected === n.id;
          return (
            <div
              key={n.id}
              data-node={n.id}
              className="absolute"
              style={{ left: p.x * scale, top: p.y * scale, width: NODE_W * scale, height: NODE_H * scale }}
            >
              <button
                type="button"
                aria-pressed={on}
                aria-label={`${meta?.label ?? n.type} (${n.id})${st ? `: ${st.text}` : ""}`}
                title={bad ? errors[n.id].join("\n") : undefined}
                onPointerDown={(e) => startDrag(e, n.id)}
                onClick={() => { onSelect?.(n.id); onSelectEdge?.(null); }}
                className={cn(
                  "flex h-full w-full origin-top-left flex-col justify-center rounded-lg border px-3 text-left shadow-sm",
                  editable ? "cursor-grab active:cursor-grabbing" : "cursor-pointer",
                  st ? TONE_BORDER[st.tone] : "border-line-strong bg-canvas",
                  bad && "border-error ring-1 ring-error",
                  on && "ring-2 ring-accent",
                )}
                style={scale !== 1 ? { transform: `scale(${scale})`, width: NODE_W, height: NODE_H } : undefined}
              >
                <span className="flex items-center justify-between gap-2 text-[10px] font-semibold uppercase tracking-wider text-ink-3">
                  <span className="truncate">{meta?.category ?? "Step"}</span>
                  <span className="shrink-0 normal-case tracking-normal">{meta?.perVideo === false ? "once per run" : "per video"}</span>
                </span>
                <span className="truncate text-[13px] font-semibold text-ink">{meta?.label ?? n.type}</span>
                <span className={cn("truncate text-[11px]", st ? TONE_TEXT[st.tone] : "text-ink-3")}>
                  {st ? st.text : `${n.id}${n.retries ? ` · retries ${n.retries}` : ""}`}
                </span>
              </button>
              {editable ? (
                <span
                  role="button"
                  tabIndex={-1}
                  aria-label={`Connect ${meta?.label ?? n.type} to another step`}
                  onPointerDown={(e) => startLink(e, n.id)}
                  className="absolute -right-2 top-1/2 size-4 -translate-y-1/2 cursor-crosshair rounded-full border-2 border-canvas bg-accent shadow"
                />
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}
