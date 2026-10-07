import { cn } from "@/lib/cn";
import { PROGRESS_ORDER, STEP_LABEL } from "@/lib/pipelines";

const BAR: Record<string, string> = {
  succeeded: "bg-success",
  skipped: "bg-ink-3",
  running: "bg-running",
  queued: "bg-line-strong",
  retry_wait: "bg-warning",
  failed: "bg-error",
  pending: "bg-hover",
  cancelled: "bg-line",
};

/** Steps by status as one bar (2px gaps). */
export function ProgressBar({ counts, className }: { counts: Record<string, number>; className?: string }) {
  const total = Object.values(counts).reduce((a, b) => a + b, 0) || 1;
  const label = PROGRESS_ORDER.filter((s) => counts[s]).map((s) => `${STEP_LABEL[s]} ${counts[s]}`).join(", ");
  return (
    <div role="img" aria-label={label || "No steps"} className={cn("flex h-1.5 w-full gap-[2px] overflow-hidden rounded-full bg-hover", className)}>
      {PROGRESS_ORDER.filter((s) => counts[s]).map((s) => (
        <span key={s} className={cn("h-full first:rounded-l-full last:rounded-r-full", BAR[s])} style={{ width: `${(counts[s] / total) * 100}%` }} />
      ))}
    </div>
  );
}

