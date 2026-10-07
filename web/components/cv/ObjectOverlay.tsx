"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import { browserApi } from "@/lib/api/browser";
import type { FrameObjects, RunObjects } from "@/lib/api/types";
import { useFrame, type FrameStore } from "@/lib/inspector/frameStore";

/** Frames of boxes fetched per request; the overlay reads from the window around the playhead. */
const WINDOW = 600;

/**
 * Object boxes from an object-detection run for the frame on screen: dashed, in the AI colour, labelled with
 * the label, track ID, and score (so they read apart from the solid hand skeletons without another colour).
 * `highlight` picks one track to emphasise (e.g. the object of a movement event).
 */
export function ObjectOverlay({ runId, frameStore, highlight }: { runId: string; frameStore: FrameStore; highlight?: number | null }) {
  const chunk = useSyncExternalStore(frameStore.subscribe, () => Math.floor(frameStore.get() / WINDOW), () => 0);
  const [data, setData] = useState<{ chunk: number; runId: string; frames: Map<number, FrameObjects> } | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    browserApi<RunObjects>(`/cv/runs/${runId}/objects`, {
      query: { frame_from: chunk * WINDOW, frame_to: chunk * WINDOW + WINDOW - 1 },
      signal: ctrl.signal,
    })
      .then((res) => res.ok && setData({ chunk, runId, frames: new Map(res.data.frames.map((f) => [f.frame, f])) }))
      .catch(() => undefined);
    return () => ctrl.abort();
  }, [runId, chunk]);

  const frame = useFrame(frameStore);
  const current = data && data.runId === runId ? data.frames.get(frame) : undefined;
  if (!current) return null;
  return (
    <div className="pointer-events-none absolute inset-0" data-testid="object-overlay" data-objects={current.objects.length}>
      {current.objects.map((o) => {
        const [x, y, w, h] = o.bbox;
        const dim = highlight != null && highlight !== o.track_id;
        return (
          <div
            key={o.track_id}
            data-track={o.track_id}
            className="absolute rounded-[3px] border-2 border-dashed border-ai"
            style={{ left: `${x * 100}%`, top: `${y * 100}%`, width: `${w * 100}%`, height: `${h * 100}%`, opacity: dim ? 0.35 : 1 }}
          >
            <span className="absolute -top-px left-0 -translate-y-full whitespace-nowrap rounded-sm border border-ai-line bg-canvas/95 px-1 text-[10.5px] font-semibold leading-4 text-ink">
              {o.label} #{o.track_id} · {o.score.toFixed(2)}
            </span>
          </div>
        );
      })}
    </div>
  );
}
