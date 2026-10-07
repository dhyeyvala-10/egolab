import { cn } from "@/lib/cn";

export type StatusTone = "success" | "warning" | "error" | "running" | "neutral";

/** Maps the status strings used across jobs, events, and review to a tone. */
const STATUS_TONES: Record<string, StatusTone> = {
  // jobs
  queued: "neutral",
  waiting: "neutral", // a run waiting on the runs it reads (spec Phase 4)
  running: "running",
  succeeded: "success",
  completed: "success",
  failed: "error",
  cancelled: "neutral",
  retrying: "warning",
  // movement events / review (spec Phase 4)
  auto_detected: "neutral",
  needs_review: "warning",
  confirmed: "success",
  rejected: "error",
  corrected: "success",
  // videos and uploads (spec Phase 1)
  uploaded: "neutral",
  processing: "running",
  ready: "success",
  uploading: "running",
  processed: "success",
  aborted: "neutral",
  paused: "neutral",
  awaiting_approval: "warning", // over the admin's limit, waiting for them
  held: "warning",
  // people
  pending: "warning",
  // annotation queue (spec Phase 2)
  todo: "neutral",
  in_progress: "running",
  done: "success",
  // quality
  corrupt: "error",
  duplicate: "warning",
  ok: "success",
};

const TONE_CLASSES: Record<StatusTone, string> = {
  success: "text-success bg-success-bg border-success-line",
  warning: "text-warning bg-warning-bg border-warning-line",
  error: "text-error bg-error-bg border-error-line",
  running: "text-running bg-running-bg border-running-line",
  neutral: "text-ink-2 bg-hover border-line",
};

export function statusTone(status: string): StatusTone {
  return STATUS_TONES[status] ?? "neutral";
}

export function humanizeStatus(status: string): string {
  const s = status.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export interface StatusBadgeProps {
  status: string;
  /** Override the displayed label (defaults to the humanized status). */
  label?: string;
  /** Override the tone inferred from `status`. */
  tone?: StatusTone;
  className?: string;
}

export function StatusBadge({ status, label, tone, className }: StatusBadgeProps) {
  const t = tone ?? statusTone(status);
  return (
    <span
      data-tone={t}
      className={cn(
        "inline-flex h-[22px] items-center gap-1.5 whitespace-nowrap rounded-full border px-2 text-[11.5px] font-semibold",
        TONE_CLASSES[t],
        className,
      )}
    >
      <span aria-hidden className={cn("size-1.5 rounded-full bg-current", t === "running" && "animate-pulse")} />
      {label ?? humanizeStatus(status)}
    </span>
  );
}
