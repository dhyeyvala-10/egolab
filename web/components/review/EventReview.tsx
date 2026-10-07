"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { ReviewButtons } from "@/components/movement/ReviewButtons";
import { browserApi } from "@/lib/api/browser";
import type { CorrectionResult, MovementClassRead, MovementEventDetail } from "@/lib/api/types";
import { CorrectForm } from "./CorrectForm";

/** Review one event from its page: accept / flag / reject, or correct it (which opens the new version). */
export function EventReview({ event, classes }: { event: MovementEventDetail; classes: MovementClassRead[] }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  if (event.superseded_at) return null;
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <ReviewButtons eventId={event.id} status={event.status} />
        {!open ? <button type="button" onClick={() => setOpen(true)} className="h-[30px] rounded-md border border-line-strong px-3 text-xs font-semibold hover:bg-hover">Correct…</button> : null}
      </div>
      {open ? (
        <CorrectForm event={event} classes={classes} onCancel={() => setOpen(false)}
          onSubmit={async (body) => {
            const res = await browserApi<CorrectionResult>(`/review/events/${event.id}/correct`, { method: "POST", body });
            if (!res.ok) return res.message;
            router.push(`/cv/movements/events/${res.data.event.id}`);
            return null;
          }} />
      ) : null}
    </div>
  );
}
