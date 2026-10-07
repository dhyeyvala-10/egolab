"use client";

import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { browserApi } from "@/lib/api/browser";
import type { RunSeries, SeriesPoint } from "@/lib/api/types";
import { cn } from "@/lib/cn";

type Metric = "speed" | "accel" | "visibility";

const METRICS: { value: Metric; label: string }[] = [
  { value: "speed", label: "Speed" },
  { value: "accel", label: "Acceleration" },
  { value: "visibility", label: "Visibility" },
];

const PLOT_H = 96;
const AXIS_H = 18;
const LEFT = 44;
const fmt = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

/** Smallest "nice" number (1, 2, 2.5, 5 × 10ⁿ) at or above v. */
export function niceCeil(v: number): number {
  if (!(v > 0)) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  return ([1, 2, 2.5, 5, 10].find((m) => m * p >= v) ?? 10) * p;
}

function formatValue(v: number, metric: Metric): string {
  return metric === "visibility" ? `${Math.round(v * 100)}%` : fmt.format(v);
}

/** Path segments, broken where the track has no samples (a gap wider than two buckets). */
function segments(points: SeriesPoint[], gap: number): SeriesPoint[][] {
  const out: SeriesPoint[][] = [];
  for (const p of points) {
    const last = out.at(-1)?.at(-1);
    if (!last || p.t - last.t > gap) out.push([p]);
    else out.at(-1)!.push(p);
  }
  return out;
}

function Multiple({
  name,
  points,
  metric,
  unit,
  yMax,
  t0,
  t1,
  hover,
  onHover,
  width,
}: {
  name: string;
  points: SeriesPoint[];
  metric: Metric;
  unit: string;
  yMax: number;
  t0: number;
  t1: number;
  hover: number | null;
  onHover: (t: number | null) => void;
  width: number;
}) {
  const plotW = Math.max(40, width - LEFT - 8);
  const x = (t: number) => LEFT + ((t - t0) / Math.max(1e-6, t1 - t0)) * plotW;
  const y = (v: number) => PLOT_H - (Math.min(v, yMax) / yMax) * (PLOT_H - 6) + 2;
  const step = points.length > 1 ? (t1 - t0) / points.length : 1;
  const segs = segments(points, step * 2.5);
  const nearest = hover == null || !points.length ? null : points.reduce((a, b) => (Math.abs(b.t - hover) < Math.abs(a.t - hover) ? b : a));
  const peak = points.reduce<SeriesPoint | null>((a, b) => (!a || b.max > a.max ? b : a), null);
  const ticks = [0, yMax / 2, yMax];

  return (
    <figure className="m-0 min-w-0 rounded-md border border-line px-2 pb-1 pt-2" data-series={name}>
      <figcaption className="flex items-baseline justify-between gap-2 px-1 text-xs">
        <span className="font-semibold capitalize text-ink">{name}</span>
        <span className="tabular-nums text-ink-2">
          {nearest ? (
            <>
              <strong className="text-ink">{formatValue(nearest.mean, metric)}</strong> {metric === "visibility" ? "" : unit} at {nearest.t.toFixed(2)} s
            </>
          ) : peak ? (
            <>
              peak <strong className="text-ink">{formatValue(peak.max, metric)}</strong> {metric === "visibility" ? "" : unit}
            </>
          ) : (
            "no samples"
          )}
        </span>
      </figcaption>
      <svg width={width} height={PLOT_H + AXIS_H} role="img" aria-label={`${name} ${metric} over time`} className="block overflow-visible"
           onPointerMove={(e: PointerEvent<SVGSVGElement>) => {
             const r = e.currentTarget.getBoundingClientRect();
             const px = e.clientX - r.left;
             if (px < LEFT) return onHover(null);
             onHover(t0 + ((px - LEFT) / plotW) * (t1 - t0));
           }}
           onPointerLeave={() => onHover(null)}>
        {ticks.map((v) => (
          <g key={v}>
            <line x1={LEFT} x2={LEFT + plotW} y1={y(v)} y2={y(v)} stroke="var(--color-line)" strokeWidth={1} />
            <text x={LEFT - 6} y={y(v) + 3} textAnchor="end" className="fill-ink-3 font-mono text-[10px] tabular-nums">
              {formatValue(v, metric)}
            </text>
          </g>
        ))}
        {segs.map((seg, i) => (
          <g key={i}>
            <path
              d={`M${seg.map((p) => `${x(p.t)},${y(p.max)}`).join("L")}L${[...seg].reverse().map((p) => `${x(p.t)},${y(p.min)}`).join("L")}Z`}
              fill="var(--color-ai)"
              fillOpacity={0.1}
            />
            <path d={`M${seg.map((p) => `${x(p.t)},${y(p.mean)}`).join("L")}`} fill="none" stroke="var(--color-ai)" strokeWidth={2}
                  strokeLinejoin="round" strokeLinecap="round" />
          </g>
        ))}
        {[t0, (t0 + t1) / 2, t1].map((t, i) => (
          <text key={i} x={x(t)} y={PLOT_H + 13} textAnchor={i === 0 ? "start" : i === 2 ? "end" : "middle"} className="fill-ink-3 font-mono text-[10px] tabular-nums">
            {t.toFixed(1)} s
          </text>
        ))}
        {nearest ? (
          <g pointerEvents="none">
            <line x1={x(nearest.t)} x2={x(nearest.t)} y1={0} y2={PLOT_H} stroke="var(--color-ink-3)" strokeWidth={1} />
            <circle cx={x(nearest.t)} cy={y(nearest.mean)} r={6} fill="var(--color-canvas)" />
            <circle cx={x(nearest.t)} cy={y(nearest.mean)} r={4} fill="var(--color-ai)" />
          </g>
        ) : null}
      </svg>
    </figure>
  );
}

/**
 * Per-finger small multiples for one track: the band is min–max per time bucket, the line the mean. All
 * panels share one y-scale so fingers compare directly.
 */
export function FingerCharts({ runId, trackId }: { runId: string; trackId: number }) {
  const [metric, setMetric] = useState<Metric>("speed");
  const [data, setData] = useState<RunSeries | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hover, setHover] = useState<number | null>(null);
  const [table, setTable] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(360);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      const cols = el.clientWidth >= 720 ? 2 : 1;
      setWidth(Math.floor((el.clientWidth - (cols - 1) * 12) / cols) - 18);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const ctrl = new AbortController();
    browserApi<RunSeries>(`/cv/runs/${runId}/series`, { query: { track_id: trackId, metric, buckets: 300 }, signal: ctrl.signal })
      .then((res) => {
        if (res.ok) {
          setData(res.data);
          setError(null);
        } else setError(res.message);
      })
      .catch(() => undefined);
    return () => ctrl.abort();
  }, [runId, trackId, metric]);

  const scale = useMemo(() => {
    const all = data?.series.flatMap((s) => s.points) ?? [];
    if (!all.length) return null;
    return {
      t0: Math.min(...all.map((p) => p.t)),
      t1: Math.max(...all.map((p) => p.t)),
      yMax: metric === "visibility" ? 1 : niceCeil(Math.max(...all.map((p) => p.max))),
    };
  }, [data, metric]);

  const allTimes = useMemo(() => [...new Set(data?.series.flatMap((s) => s.points.map((p) => p.t)) ?? [])].sort((a, b) => a - b), [data]);
  const onKey = (e: KeyboardEvent) => {
    if (!allTimes.length || (e.key !== "ArrowLeft" && e.key !== "ArrowRight")) return;
    e.preventDefault();
    e.stopPropagation();
    const i = hover == null ? 0 : allTimes.findIndex((t) => t >= hover);
    const next = Math.min(allTimes.length - 1, Math.max(0, (i < 0 ? allTimes.length - 1 : i) + (e.key === "ArrowRight" ? 1 : -1)));
    setHover(allTimes[next]);
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <div className="flex overflow-hidden rounded-md border border-line" role="radiogroup" aria-label="Metric">
          {METRICS.map((m) => (
            <button key={m.value} type="button" role="radio" aria-checked={metric === m.value} onClick={() => setMetric(m.value)}
                    className={cn("h-7 px-2.5 font-medium", metric === m.value ? "bg-ink text-canvas" : "hover:bg-hover")}>
              {m.label}
            </button>
          ))}
        </div>
        <span className="text-ink-3">
          {data ? `${data.unit} · band = range within each time bucket, line = mean` : "Loading…"}
        </span>
        <label className="ml-auto flex items-center gap-1.5 text-ink-2">
          <input type="checkbox" checked={table} onChange={(e) => setTable(e.target.checked)} /> Table view
        </label>
      </div>
      {error ? <p className="text-xs text-error">{error}</p> : null}
      <div ref={box} tabIndex={0} onKeyDown={onKey} aria-label="Finger charts; use ← and → to move the crosshair"
           className={cn("grid gap-3 outline-offset-4 md:grid-cols-2", !data && "opacity-60")} data-testid="finger-charts">
        {data && scale && !table
          ? data.series.map((s) => (
              <Multiple key={s.name} name={s.name} points={s.points} metric={metric} unit={data.unit} yMax={scale.yMax} t0={scale.t0} t1={scale.t1}
                        hover={hover} onHover={setHover} width={width} />
            ))
          : null}
      </div>
      {data && table ? (
        <div className="max-h-96 overflow-auto rounded-md border border-line">
          <table className="w-full border-collapse text-xs">
            <thead className="sticky top-0 bg-subtle">
              <tr>
                <th className="px-2 py-1.5 text-left font-semibold text-ink-3">Time</th>
                <th className="px-2 py-1.5 text-left font-semibold text-ink-3">Frames</th>
                {data.series.map((s) => <th key={s.name} className="px-2 py-1.5 text-right font-semibold capitalize text-ink-3">{s.name} (mean)</th>)}
              </tr>
            </thead>
            <tbody>
              {(data.series[0]?.points ?? []).map((p, i) => (
                <tr key={p.frame_start} className="border-t border-line">
                  <td className="px-2 py-1 font-mono tabular-nums">{p.t.toFixed(2)} s</td>
                  <td className="px-2 py-1 font-mono tabular-nums">f{p.frame_start}–f{p.frame_end}</td>
                  {data.series.map((s) => (
                    <td key={s.name} className="px-2 py-1 text-right tabular-nums">{s.points[i] ? formatValue(s.points[i].mean, metric) : "—"}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
