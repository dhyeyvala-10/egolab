import { cn } from "@/lib/cn";

export type ConfidenceLevel = "high" | "medium" | "low";

/** Thresholds for colouring model confidence. Tune per model once evaluation data exists (Phase 8). */
export const CONFIDENCE_THRESHOLDS = { high: 0.85, medium: 0.6 } as const;

export function confidenceLevel(value: number): ConfidenceLevel {
  if (value >= CONFIDENCE_THRESHOLDS.high) return "high";
  if (value >= CONFIDENCE_THRESHOLDS.medium) return "medium";
  return "low";
}

const LEVEL_CLASSES: Record<ConfidenceLevel, string> = {
  high: "text-success bg-success-bg border-success-line",
  medium: "text-warning bg-warning-bg border-warning-line",
  low: "text-error bg-error-bg border-error-line",
};

export interface ConfidenceBadgeProps {
  /** Model confidence in [0, 1]. */
  value: number;
  /** Model version that produced the prediction (principle 8: every prediction carries one). */
  modelVersion?: string;
  className?: string;
}

export function ConfidenceBadge({ value, modelVersion, className }: ConfidenceBadgeProps) {
  const clamped = Math.min(1, Math.max(0, value));
  const level = confidenceLevel(clamped);
  return (
    <span
      data-level={level}
      title={modelVersion ? `Confidence ${clamped.toFixed(3)} · ${modelVersion}` : `Confidence ${clamped.toFixed(3)}`}
      className={cn(
        "inline-flex h-[22px] items-center rounded border px-1.5 font-mono text-[11.5px] font-medium tabular-nums",
        LEVEL_CLASSES[level],
        className,
      )}
    >
      {clamped.toFixed(2)}
    </span>
  );
}
