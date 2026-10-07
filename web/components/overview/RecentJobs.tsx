"use client";

import { useState } from "react";
import { EmptyState, StatusBadge } from "@/components/ui";
import type { JobSummary } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { formatDateTime } from "@/lib/format";

type JobFilter = "all" | "active" | "failed" | "succeeded";

const FILTERS: { id: JobFilter; label: string; match: (j: JobSummary) => boolean }[] = [
  { id: "all", label: "All", match: () => true },
  { id: "active", label: "Active", match: (j) => j.status === "queued" || j.status === "running" || j.status === "retrying" },
  { id: "failed", label: "Failed", match: (j) => j.status === "failed" },
  { id: "succeeded", label: "Succeeded", match: (j) => j.status === "succeeded" },
];

/** Latest jobs returned by the overview endpoint (already limited server-side), filterable by status. */
export function RecentJobs({ jobs, unavailable }: { jobs: JobSummary[]; unavailable?: boolean }) {
  const [filter, setFilter] = useState<JobFilter>("all");
  const shown = jobs.filter(FILTERS.find((f) => f.id === filter)!.match);

  return (
    <section aria-labelledby="jobs-title" className="flex min-w-0 flex-col gap-4 rounded-3xl border border-line bg-canvas p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="jobs-title" className="text-lg font-extrabold tracking-tight">
          Jobs in motion
        </h2>
        <div role="group" aria-label="Filter jobs by status" className="flex flex-wrap gap-1.5">
          {FILTERS.map((f) => {
            const on = f.id === filter;
            return (
              <button
                key={f.id}
                type="button"
                aria-pressed={on}
                onClick={() => setFilter(f.id)}
                className={cn(
                  "flex h-8 items-center gap-1.5 rounded-full border px-3 text-xs font-semibold",
                  on ? "border-ink bg-ink text-ground" : "border-line text-ink-2 hover:bg-hover hover:text-ink",
                )}
              >
                {f.label}
                <span className={cn("tabular-nums", on ? "text-ground/70" : "text-ink-3")}>{jobs.filter(f.match).length}</span>
              </button>
            );
          })}
        </div>
      </div>

      {shown.length > 0 ? (
        <ul className="flex flex-col gap-2">
          {shown.map((j) => (
            <li key={j.id} className="flex items-center gap-4 rounded-2xl bg-ground px-4 py-3">
              <div className="flex min-w-0 flex-1 flex-col">
                <span className="truncate font-semibold">{j.type}</span>
                {j.error ? (
                  <span className="text-xs text-error">{j.error}</span>
                ) : (
                  <span className="text-xs text-ink-3">
                    <span className="tabular-nums">{formatDateTime(j.created_at)}</span> ·{" "}
                    <span className="font-mono">{j.id.slice(0, 8)}</span>
                  </span>
                )}
              </div>
              <StatusBadge status={j.status} />
            </li>
          ))}
        </ul>
      ) : (
        <EmptyState
          size="compact"
          title={unavailable ? "Jobs unavailable" : jobs.length > 0 ? "No jobs with this status" : "No jobs yet"}
          description={unavailable ? "Connect the API to see processing jobs." : "Jobs appear here when videos are ingested and processed."}
        />
      )}
    </section>
  );
}
