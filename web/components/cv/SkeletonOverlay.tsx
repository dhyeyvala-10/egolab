"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import { browserApi } from "@/lib/api/browser";
import type { FrameHands, RunFrames } from "@/lib/api/types";
import { CONNECTIONS, TIPS } from "@/lib/cv/skeleton";
import { useFrame, type FrameStore } from "@/lib/inspector/frameStore";

/** Frames of keypoints fetched per request; the overlay reads from the window around the playhead. */
const WINDOW = 600;

/**
 * Hand skeletons from a tracking run, drawn over the player for the frame on screen. Coordinates are
 * fractions of the frame, so this sits inside the player's picture box at any size.
 */
export function SkeletonOverlay({ runId, frameStore, aspect }: { runId: string; frameStore: FrameStore; aspect: number }) {
  const chunk = useSyncExternalStore(frameStore.subscribe, () => Math.floor(frameStore.get() / WINDOW), () => 0);
  const [data, setData] = useState<{ chunk: number; runId: string; frames: Map<number, FrameHands> } | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    browserApi<RunFrames>(`/cv/runs/${runId}/frames`, {
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
  const h = 1000 / aspect;

  return (
    <div className="pointer-events-none absolute inset-0" data-testid="skeleton-overlay" data-hands={current.hands.length}>
      <svg viewBox={`0 0 1000 ${h}`} preserveAspectRatio="none" className="absolute inset-0 size-full">
        {current.hands.map((hand) => {
          const pts = hand.keypoints.map(([x, y]) => [x * 1000, y * h] as const);
          const occluded = new Set(hand.fingers.filter((f) => f.occluded).map((f) => f.finger));
          return (
            <g key={hand.track_id} data-track={hand.track_id}>
              {CONNECTIONS.map(([a, b]) => (
                <line key={`${a}-${b}`} x1={pts[a][0]} y1={pts[a][1]} x2={pts[b][0]} y2={pts[b][1]}
                      stroke="var(--color-ai)" strokeWidth={2} strokeLinecap="round" vectorEffect="non-scaling-stroke" />
              ))}
              {pts.map(([x, y], i) => {
                const hidden = TIPS[i] && occluded.has(TIPS[i]);
                return (
                  <g key={i}>
                    {/* 2px surface ring, then the joint: 8px dot (hollow when the fingertip is estimated hidden). */}
                    <line x1={x} y1={y} x2={x} y2={y} stroke="#ffffff" strokeWidth={12} strokeLinecap="round" vectorEffect="non-scaling-stroke" />
                    <line x1={x} y1={y} x2={x} y2={y} stroke="var(--color-ai)" strokeWidth={8} strokeLinecap="round" vectorEffect="non-scaling-stroke" />
                    {hidden ? <line x1={x} y1={y} x2={x} y2={y} stroke="#ffffff" strokeWidth={4} strokeLinecap="round" vectorEffect="non-scaling-stroke" /> : null}
                  </g>
                );
              })}
            </g>
          );
        })}
      </svg>
      {current.hands.map((hand) => {
        const [x, y] = hand.keypoints[0];
        return (
          <span
            key={hand.track_id}
            className="absolute -translate-x-1/2 translate-y-2 whitespace-nowrap rounded-sm border border-ai-line bg-canvas/95 px-1 text-[10.5px] font-semibold leading-4 text-ink"
            style={{ left: `${x * 100}%`, top: `${y * 100}%` }}
          >
            {hand.handedness === "left" ? "L" : "R"} #{hand.track_id} · {hand.confidence.toFixed(2)}
          </span>
        );
      })}
    </div>
  );
}
