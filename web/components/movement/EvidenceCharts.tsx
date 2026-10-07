"use client";

import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { measurementLabel, measurementUnit, thresholdFor } from "@/lib/cv/evidence";

const H = 92;
const AXIS = 16;
const LEFT = 48;
const fmt = (v: number) => (Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2));

function Chart({ name, frames, values, threshold, hover, onHover, onPick, width }: {
  name: string;
  frames: number[];
  values: number[];
  threshold: number | null;
  hover: number | null;
  onHover: (i: number | null) => void;
  onPick: (frame: number) => void;
  width: number;
}) {
  const plotW = Math.max(60, width - LEFT - 10);
  const all = threshold != null ? [...values, threshold] : values;
  let lo = Math.min(...all);
  let hi = Math.max(...all);
  if (hi - lo < 1e-9) { lo -= 1; hi += 1; }
  const pad = (hi - lo) * 0.08;
  lo -= pad; hi += pad;
  const f0 = frames[0];
  const f1 = frames[frames.length - 1];
  const x = (f: number) => LEFT + ((f - f0) / Math.max(1, f1 - f0)) * plotW;
  const y = (v: number) => 4 + (1 - (v - lo) / (hi - lo)) * (H - 8);
  const idx = (px: number) => {
    const f = f0 + ((px - LEFT) / plotW) * (f1 - f0);
    let best = 0;
    for (let i = 1; i < frames.length; i++) if (Math.abs(frames[i] - f) < Math.abs(frames[best] - f)) best = i;
    return best;
  };
  // Break the line where evidence frames skip (a stride or a dropped detection).
  const d = frames.map((f, i) => `${i && f - frames[i - 1] <= 3 ? "L" : "M"}${x(f)},${y(values[i])}`).join("");
  const unit = measurementUnit(name);
  const i = hover;
  return (
    <figure className="m-0 min-w-0 rounded-md border border-line px-2 pb-1 pt-2" data-measurement={name}>
      <figcaption className="flex items-baseline justify-between gap-2 px-1 text-xs">
        <span className="font-semibold text-ink">{measurementLabel(name)}{unit ? <span className="font-normal text-ink-3"> · {unit}</span> : null}</span>
        <span className="tabular-nums text-ink-2">
          {i != null ? <><strong className="text-ink">{fmt(values[i])}</strong> at f{frames[i]}</> : threshold != null ? <>threshold <strong className="text-ink">{fmt(threshold)}</strong></> : `${frames.length} frames`}
        </span>
      </figcaption>
      <svg width={width} height={H + AXIS} role="img" aria-label={`${measurementLabel(name)} per evidence frame`} className="block overflow-visible"
           onPointerMove={(e: PointerEvent<SVGSVGElement>) => { const px = e.clientX - e.currentTarget.getBoundingClientRect().left; onHover(px < LEFT ? null : idx(px)); }}
           onPointerLeave={() => onHover(null)}
           onClick={(e) => { const px = e.clientX - e.currentTarget.getBoundingClientRect().left; if (px >= LEFT) onPick(frames[idx(px)]); }}>
        {[hi - pad, lo + pad].map((v) => (
          <g key={v}>
            <line x1={LEFT} x2={LEFT + plotW} y1={y(v)} y2={y(v)} stroke="var(--color-line)" />
            <text x={LEFT - 6} y={y(v) + 3} textAnchor="end" className="fill-ink-3 font-mono text-[10px] tabular-nums">{fmt(v)}</text>
          </g>
        ))}
        {threshold != null ? (
          <g>
            <line x1={LEFT} x2={LEFT + plotW} y1={y(threshold)} y2={y(threshold)} stroke="var(--color-ink-2)" strokeDasharray="4 3" />
            <text x={LEFT + plotW} y={y(threshold) - 3} textAnchor="end" className="fill-ink-2 text-[10px]">threshold</text>
          </g>
        ) : null}
        <path d={d} fill="none" stroke="var(--color-ai)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        {frames.length <= 12 ? frames.map((f, k) => <circle key={f} cx={x(f)} cy={y(values[k])} r={3} fill="var(--color-ai)" stroke="var(--color-canvas)" strokeWidth={1.5} />) : null}
        <text x={LEFT} y={H + 12} className="fill-ink-3 font-mono text-[10px]">f{f0}</text>
        <text x={LEFT + plotW} y={H + 12} textAnchor="end" className="fill-ink-3 font-mono text-[10px]">f{f1}</text>
        {i != null ? (
          <g pointerEvents="none">
            <line x1={x(frames[i])} x2={x(frames[i])} y1={0} y2={H} stroke="var(--color-ink-3)" />
            <circle cx={x(frames[i])} cy={y(values[i])} r={6} fill="var(--color-canvas)" />
            <circle cx={x(frames[i])} cy={y(values[i])} r={4} fill="var(--color-ai)" />
          </g>
        ) : null}
      </svg>
    </figure>
  );
}

/**
 * One chart per measurement the rule compared (they have different units, so each has its own scale),
 * over the event's evidence frames, with the threshold it was held to. Hovering, or ← / → with the charts
 * focused, moves a shared crosshair; clicking a point shows that frame in the player.
 */
export function EvidenceCharts({ className, frames, measurements, thresholds, onPick }: {
  className: string;
  frames: number[];
  measurements: Record<string, number[]>;
  thresholds: Record<string, number>;
  onPick: (frame: number) => void;
}) {
  const names = useMemo(() => Object.keys(measurements).filter((k) => measurements[k].length === frames.length && frames.length > 0), [measurements, frames]);
  const [hover, setHover] = useState<number | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(360);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      const cols = el.clientWidth >= 720 && names.length > 1 ? 2 : 1;
      setWidth(Math.floor((el.clientWidth - (cols - 1) * 12) / cols) - 18);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [names.length]);
  const onKey = (e: KeyboardEvent) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    e.stopPropagation();
    const next = Math.min(frames.length - 1, Math.max(0, (hover ?? -1) + (e.key === "ArrowRight" ? 1 : -1)));
    setHover(next);
    onPick(frames[next]);
  };
  if (!names.length) return <p className="py-2 text-xs text-ink-3">This classifier recorded no per-frame measurements for the event.</p>;
  return (
    <div ref={box} tabIndex={0} onKeyDown={onKey} aria-label="Evidence charts; use ← and → to step through the evidence frames"
         className="grid gap-3 outline-offset-4 md:grid-cols-2" data-testid="evidence-charts">
      {names.map((n) => (
        <Chart key={n} name={n} frames={frames} values={measurements[n]} threshold={thresholdFor(className, n, thresholds)}
               hover={hover} onHover={setHover} onPick={onPick} width={width} />
      ))}
    </div>
  );
}
