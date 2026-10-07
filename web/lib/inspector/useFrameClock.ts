"use client";

import { useEffect, useState } from "react";
import { browserApi } from "@/lib/api/browser";
import type { FrameIndex, VideoDetail } from "@/lib/api/types";
import { clockFromIndex, nominalClock, type FrameClock } from "./frames";

export type ClockState = { state: "loading" } | { state: "exact"; clock: FrameClock } | { state: "nominal"; clock: FrameClock; reason: string };

/** The video's frame clock: exact from its frame index, else nominal FPS (flagged). */
export function useFrameClock(video: VideoDetail): ClockState {
  const proxy = (video.derivatives?.proxy ?? {}) as { frame_count?: number; fps?: number };
  const fps = video.fps ?? proxy.fps ?? 30;
  const count = video.frame_count ?? proxy.frame_count ?? Math.max(1, Math.round((video.duration_s ?? 0) * fps));
  const [state, setState] = useState<ClockState>({ state: "loading" });
  useEffect(() => {
    const ctrl = new AbortController();
    browserApi<FrameIndex>(`/videos/${video.id}/frame-index`, { signal: ctrl.signal })
      .then((res) =>
        setState(res.ok ? { state: "exact", clock: clockFromIndex(res.data) } : { state: "nominal", clock: nominalClock(count, fps), reason: res.message }),
      )
      .catch(() => undefined);
    return () => ctrl.abort();
  }, [video.id, count, fps]);
  return state;
}
