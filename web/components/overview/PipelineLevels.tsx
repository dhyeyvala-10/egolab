import Link from "next/link";
import { cn } from "@/lib/cn";
import { PIPELINE } from "@/lib/pipeline";
import type { LevelCount } from "@/lib/pipelineCounts";

const numberFormat = new Intl.NumberFormat("en-US");

/**
 * The pipeline as a staircase: one step per level, rising left to right, each showing how much data
 * has reached it and linking to where that level's work happens. Planned levels are outlined.
 */
export function PipelineLevels({ counts }: { counts: Record<string, LevelCount> | null }) {
  return (
    <section aria-labelledby="levels-title" className="flex flex-col gap-4 rounded-3xl border border-line bg-canvas p-5 md:p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="levels-title" className="text-lg font-extrabold tracking-tight">
          Where your data is, level by level
        </h2>
        <span className="font-mono text-xs text-ink-3">Raw video at the bottom, exported data at the top</span>
      </div>
      <ol className="flex items-end gap-2 overflow-x-auto pb-1">
        {PIPELINE.map((level, i) => {
          const planned = level.status === "planned";
          const count = counts?.[level.name];
          return (
            <li key={level.name} className="min-w-[112px] flex-1">
              <Link
                href={level.pages[0].href}
                style={{ height: 96 + i * 12 }}
                className={cn(
                  "flex flex-col justify-between rounded-t-2xl rounded-b-md border p-3 transition-colors",
                  planned
                    ? "border-dashed border-line-strong text-ink-3 hover:bg-hover"
                    : "border-line bg-ground hover:border-accent hover:bg-accent-soft",
                )}
              >
                <span className="flex flex-col">
                  <span className={cn("text-[22px] font-extrabold leading-none tracking-tight tabular-nums", !planned && count?.value == null && "text-ink-3")}>
                    {count?.value == null ? "—" : numberFormat.format(count.value)}
                  </span>
                  <span className="mt-1 text-[11px] text-ink-3">{planned ? level.phases : count?.caption}</span>
                </span>
                <span className="flex items-baseline gap-1.5 text-xs font-semibold leading-tight">
                  <span className="font-mono text-[10px] text-ink-3">{String(i + 1).padStart(2, "0")}</span>
                  {level.name}
                </span>
              </Link>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
