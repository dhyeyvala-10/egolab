"use client";

import { useState } from "react";
import type { ReviewMetrics } from "@/lib/api/types";

type Day = ReviewMetrics["daily"][number];

/**
 * Reviews per day, stacked: human reviews (the human colour) under auto-accepts (the AI colour), with a
 * 2px gap between the parts, one y-axis, a legend, a hover readout, and the numbers as a table.
 */
export function DailyChart({ days }: { days: Day[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const [table, setTable] = useState(false);
  if (!days.length) return <p className="py-4 text-xs text-ink-3">No reviews in this window.</p>;
  const max = Math.max(1, ...days.map((d) => d.human + d.auto_rule));
  const H = 140, pad = 24, barW = Math.max(6, Math.min(28, 560 / days.length - 4)), step = barW + 4;
  const W = pad + days.length * step;
  const y = (v: number) => H - (v / max) * (H - 12);
  const h = hover != null ? days[hover] : null;
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
        <ul className="flex gap-3 text-ink-2" aria-label="Legend">
          <li className="flex items-center gap-1.5"><span className="size-2 rounded-sm bg-human" />Human reviews</li>
          <li className="flex items-center gap-1.5"><span className="size-2 rounded-sm bg-ai" />Auto-accepted</li>
        </ul>
        <span className="tabular-nums text-ink-2" aria-live="polite">{h ? `${h.day}: ${h.human} human, ${h.auto_rule} auto` : `${days.length} day${days.length === 1 ? "" : "s"}`}</span>
        <button type="button" onClick={() => setTable((t) => !t)} className="text-ink-3 underline">{table ? "Chart" : "Table"}</button>
      </div>
      {table ? (
        <table className="w-full text-xs"><thead className="text-left text-ink-3"><tr><th>Day</th><th className="text-right">Human</th><th className="text-right">Auto</th></tr></thead>
          <tbody>{days.map((d) => <tr key={d.day} className="border-t border-line"><td className="py-1 tabular-nums">{d.day}</td><td className="text-right tabular-nums">{d.human}</td><td className="text-right tabular-nums">{d.auto_rule}</td></tr>)}</tbody></table>
      ) : (
        <svg viewBox={`0 0 ${W} ${H + 18}`} className="h-40 w-full max-w-[640px]" role="img" aria-label="Reviews per day">
          <line x1={pad} x2={W} y1={H} y2={H} className="stroke-line" />
          <text x={pad - 4} y={y(max) + 4} textAnchor="end" className="fill-ink-3 text-[9px]">{max}</text>
          <text x={pad - 4} y={H} textAnchor="end" className="fill-ink-3 text-[9px]">0</text>
          {days.map((d, i) => {
            const x = pad + i * step + 2;
            const hy = y(d.human), ay = y(d.human + d.auto_rule);
            const gap = d.human && d.auto_rule ? 2 : 0;
            return (
              <g key={d.day} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} opacity={hover == null || hover === i ? 1 : 0.45}>
                <rect x={x - 2} y={0} width={step} height={H} fill="transparent" />
                {d.human ? <rect x={x} y={hy} width={barW} height={H - hy} rx={2} className="fill-human" /> : null}
                {d.auto_rule ? <rect x={x} y={ay} width={barW} height={Math.max(1, hy - ay - gap)} rx={2} className="fill-ai" /> : null}
                {i === 0 || i === days.length - 1 ? <text x={x + barW / 2} y={H + 13} textAnchor="middle" className="fill-ink-3 text-[9px]">{d.day.slice(5)}</text> : null}
              </g>
            );
          })}
        </svg>
      )}
    </div>
  );
}
