"use client";

import { ArrowLeft, ArrowRight } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { cn } from "@/lib/cn";
import { LEVEL_STATUS_LABEL, PIPELINE, type LevelStatus } from "@/lib/pipeline";

const STATUS_CLASSES: Record<LevelStatus, string> = {
  live: "bg-sage-soft text-sage",
  in_progress: "bg-accent-soft text-accent",
  planned: "bg-hover text-ink-3",
};

const number = (i: number) => String(i + 1).padStart(2, "0");

/** The pipeline levels as a staircase. Pick a step (or use the arrows) to read about it. */
export function PipelineStairs({ initial = 3 }: { initial?: number }) {
  const [selected, setSelected] = useState(initial);
  const level = PIPELINE[selected];
  const count = PIPELINE.length;

  return (
    <div className="flex flex-col gap-6">
      <ol aria-label="Pipeline levels" className="flex items-end gap-1.5 overflow-x-auto pb-1 md:gap-2.5">
        {PIPELINE.map((l, i) => {
          const on = i === selected;
          const planned = l.status === "planned";
          return (
            <li key={l.name} className="min-w-[96px] flex-1">
              <button
                type="button"
                aria-pressed={on}
                onClick={() => setSelected(i)}
                style={{ height: 96 + i * 26 }}
                className={cn(
                  "flex w-full flex-col items-start justify-between rounded-t-[18px] rounded-b-md border p-3 text-left transition-colors md:p-4",
                  on
                    ? "border-accent bg-accent text-on-accent"
                    : planned
                      ? "border-dashed border-line-strong text-ink-3 hover:bg-hover hover:text-ink"
                      : "border-line bg-ground hover:border-accent",
                )}
              >
                <span className="font-mono text-xs font-semibold">{number(i)}</span>
                <span className="text-[13px] font-bold leading-tight md:text-sm">{l.name}</span>
              </button>
            </li>
          );
        })}
      </ol>

      <div
        aria-live="polite"
        className="grid grid-cols-1 gap-6 rounded-3xl border border-line bg-ground p-6 md:grid-cols-[160px_minmax(0,1fr)_280px] md:gap-10 md:p-8"
      >
        <div className="text-7xl font-extrabold leading-[0.9] tracking-[-0.05em] text-accent md:text-8xl">{number(selected)}</div>
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <h3 className="text-2xl font-extrabold tracking-tight md:text-3xl">{level.name}</h3>
            <span className={cn("rounded-full px-2.5 py-1 text-xs font-bold", STATUS_CLASSES[level.status])}>
              {LEVEL_STATUS_LABEL[level.status]}
            </span>
          </div>
          <p className="max-w-[46ch] text-base text-ink-2">{level.blurb}</p>
          <div className="mt-1 flex gap-2">
            <button
              type="button"
              onClick={() => setSelected((selected + count - 1) % count)}
              aria-label="Previous level"
              className="grid size-11 place-items-center rounded-full border border-line hover:bg-hover"
            >
              <ArrowLeft className="size-4" aria-hidden />
            </button>
            <button
              type="button"
              onClick={() => setSelected((selected + 1) % count)}
              aria-label="Next level"
              className="grid size-11 place-items-center rounded-full border border-line hover:bg-hover"
            >
              <ArrowRight className="size-4" aria-hidden />
            </button>
          </div>
        </div>
        <div className="flex flex-col gap-2 border-line md:border-l md:border-dashed md:pl-7">
          <div className="font-mono text-xs text-ink-3">Where it lives · {level.phases}</div>
          <ul className="flex flex-col gap-1">
            {level.pages.map((page) => (
              <li key={page.href}>
                <Link href={page.href} className="font-semibold underline-offset-4 hover:underline">
                  {page.label}
                </Link>
                {page.built ? null : <span className="ml-1.5 font-mono text-[11px] text-ink-3">Phase {page.phase}</span>}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
