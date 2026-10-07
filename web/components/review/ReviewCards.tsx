import Link from "next/link";
import type { ReviewGroup } from "@/lib/api/types";
import { cn } from "@/lib/cn";

/** Review states in bar order, with the status colour each one means. */
const PARTS = [
  { key: "confirmed", label: "Accepted", className: "bg-success" },
  { key: "corrected", label: "Corrected", className: "bg-human" },
  { key: "rejected", label: "Rejected", className: "bg-error" },
  { key: "needs_review", label: "Needs review", className: "bg-warning" },
  { key: "open", label: "Not reviewed", className: "bg-line-strong" },
] as const;

function counts(g: ReviewGroup): Record<(typeof PARTS)[number]["key"], number> {
  return { confirmed: g.confirmed, corrected: g.corrected, rejected: g.rejected, needs_review: g.needs_review, open: g.pending - g.needs_review };
}

/** Accepted / corrected / rejected / needs review / not reviewed, as one bar with a 2px gap between parts. */
export function ProgressBar({ group, className }: { group: ReviewGroup; className?: string }) {
  const c = counts(group);
  const total = Math.max(1, group.total);
  return (
    <div className={cn("flex h-2 w-full gap-[2px] overflow-hidden rounded-full bg-hover", className)} role="img"
         aria-label={PARTS.map((p) => `${p.label} ${c[p.key]}`).join(", ")}>
      {PARTS.filter((p) => c[p.key] > 0).map((p) => (
        <span key={p.key} className={cn("h-full first:rounded-l-full last:rounded-r-full", p.className)} style={{ width: `${(c[p.key] / total) * 100}%` }}
              title={`${p.label}: ${c[p.key]}`} />
      ))}
    </div>
  );
}

export function ProgressLegend() {
  return (
    <ul className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-ink-2" aria-label="Bar colours">
      {PARTS.map((p) => (
        <li key={p.key} className="flex items-center gap-1.5"><span aria-hidden className={cn("size-2 rounded-full", p.className)} />{p.label}</li>
      ))}
    </ul>
  );
}

/**
 * One compact card per class (or object): what is left to review there, how far review has got, and the
 * way into that class's own workspace, so each kind of movement is reviewed on its own.
 */
export function ReviewCards({ groups, hrefFor }: { groups: ReviewGroup[]; hrefFor: (g: ReviewGroup) => string }) {
  return (
    <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4" data-testid="review-cards">
      {groups.map((g) => {
        const done = g.total - g.pending;
        return (
          <li key={g.key || "_none"}>
            <Link href={hrefFor(g)} data-group={g.key}
                  className="flex h-full flex-col gap-2.5 rounded-lg border border-line bg-canvas px-3.5 py-3 hover:border-line-strong hover:bg-subtle">
              <div className="flex items-baseline justify-between gap-2">
                <span className="truncate text-[13px] font-semibold">{g.label}</span>
                {g.movement_class ? <span className="font-mono text-[11px] text-ink-3">{g.movement_class.name}</span> : null}
              </div>
              <div className="flex items-baseline gap-1.5">
                <span className="text-[22px] font-semibold leading-none tabular-nums" data-testid="pending">{g.pending}</span>
                <span className="text-xs text-ink-2">to review</span>
                {g.needs_review ? <span className="ml-auto text-xs font-medium text-warning">{g.needs_review} flagged</span> : null}
              </div>
              <ProgressBar group={g} />
              <div className="flex flex-wrap justify-between gap-x-3 text-[11px] text-ink-3 tabular-nums">
                <span>{done} of {g.total} reviewed{g.auto_accepted ? ` · ${g.auto_accepted} auto` : ""}</span>
                <span>{g.min_confidence != null ? `lowest ${g.min_confidence.toFixed(2)}` : ""}</span>
              </div>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
