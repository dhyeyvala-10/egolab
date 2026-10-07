import { cn } from "@/lib/cn";

/** Annotation provenance (principle 4). */
export type AnnotationSource = "auto" | "human" | "auto_corrected";

const SOURCE: Record<AnnotationSource, { label: string; className: string }> = {
  auto: { label: "AI", className: "text-ai bg-ai-bg border-ai-line" },
  human: { label: "Human", className: "text-human bg-human-bg border-human-line" },
  auto_corrected: { label: "AI · corrected", className: "text-human bg-human-bg border-ai-line" },
};

export function SourceBadge({ source, className }: { source: AnnotationSource; className?: string }) {
  const s = SOURCE[source];
  return (
    <span
      data-source={source}
      className={cn(
        "inline-flex h-[22px] items-center whitespace-nowrap rounded border px-1.5 text-[11.5px] font-semibold",
        s.className,
        className,
      )}
    >
      {s.label}
    </span>
  );
}
