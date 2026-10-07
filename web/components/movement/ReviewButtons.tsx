"use client";

import { useState, useTransition } from "react";
import { reviewEvent } from "@/lib/actions/cv";
import type { MovementEventStatus } from "@/lib/api/types";
import { cn } from "@/lib/cn";

const ACTIONS: { status: "confirmed" | "rejected" | "needs_review"; label: string }[] = [
  { status: "confirmed", label: "Confirm" },
  { status: "needs_review", label: "Needs review" },
  { status: "rejected", label: "Reject" },
];

/** Confirm, flag, or reject an event. Rejecting takes it off the timeline; its history is kept. */
export function ReviewButtons({ eventId, status }: { eventId: string; status: MovementEventStatus }) {
  const [pending, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  if (status === "corrected") return <p className="text-xs text-ink-3">Corrected: this prediction is kept as it was, and the correction is its newer version.</p>;
  return (
    <div className="flex flex-col gap-1">
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Review">
        {ACTIONS.map((a) => (
          <button
            key={a.status}
            type="button"
            disabled={pending || status === a.status}
            aria-pressed={status === a.status}
            onClick={() => start(async () => {
              const res = await reviewEvent(eventId, a.status);
              setError(res.error ?? null);
            })}
            className={cn("h-[30px] rounded-md border px-3 text-xs font-semibold disabled:opacity-50",
              a.status === "confirmed" ? "border-ink bg-ink text-canvas" : "border-line-strong hover:bg-hover")}
          >
            {a.label}
          </button>
        ))}
      </div>
      {error ? <p className="text-xs text-error">{error}</p> : null}
    </div>
  );
}
