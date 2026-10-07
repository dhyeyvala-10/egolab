import Link from "next/link";
import { ProgressBar } from "@/components/pipelines/ProgressBar";
import { StatusBadge } from "@/components/ui";
import type { RunSummary } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { formatDuration, stepCount } from "@/lib/pipelines";

/** The latest pipeline runs on the dashboard: progress, and a way into each one. */
export function PipelineRuns({ runs, unavailable }: { runs: RunSummary[]; unavailable: boolean }) {
  return (
    <section aria-labelledby="runs-title" className="flex flex-col gap-3 rounded-3xl border border-line bg-canvas p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="runs-title" className="text-lg font-extrabold tracking-tight">Pipeline runs</h2>
        <Link href="/pipelines/runs" className="text-xs font-semibold text-ink-2 hover:underline">All runs →</Link>
      </div>
      {runs.length ? (
        <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {runs.map((r) => {
            const { done, total } = stepCount(r.counts);
            return (
              <li key={r.id}>
                <Link href={`/pipelines/runs/${r.id}`} className="flex h-full flex-col gap-2 rounded-2xl border border-line bg-ground p-3.5 hover:border-accent hover:bg-accent-soft">
                  <span className="flex items-center justify-between gap-2">
                    <span className="truncate font-semibold">{r.pipeline.name} #{r.number}</span>
                    <StatusBadge status={r.status} />
                  </span>
                  <ProgressBar counts={r.counts} />
                  <span className="text-xs text-ink-3">
                    {done}/{total} steps · {r.video_count} video{r.video_count === 1 ? "" : "s"} · {formatDuration(r.duration_s)}
                  </span>
                  <span className="text-[11px] text-ink-3">{r.started_at ? formatDateTime(r.started_at) : ""}{r.trigger === "schedule" ? " · scheduled" : r.trigger === "upload" ? " · on upload" : ""}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="py-4 text-center text-xs text-ink-3">
          {unavailable ? "Runs couldn't be loaded." : <>No pipeline runs yet. <Link href="/pipelines/templates" className="underline">Start from a template</Link>.</>}
        </p>
      )}
    </section>
  );
}
