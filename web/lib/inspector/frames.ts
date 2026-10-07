import type { FrameIndex } from "@/lib/api/types";

/**
 * Maps between frame numbers and media time for the proxy the inspector plays.
 *
 * With a frame index (the proxy's real per-frame timestamps) this is exact, including variable frame rate
 * video. Without one it falls back to nominal FPS, which the UI flags as approximate.
 */
export interface FrameClock {
  frameCount: number;
  /** True when built from the frame index. */
  exact: boolean;
  /** Presentation time of each frame, seconds, increasing. */
  times: Float64Array;
  /** Where to set `currentTime` so frame `n` is the one on screen. */
  seekTime(n: number): number;
  /** The frame on screen at media time `t` (the last frame starting at or before `t`). */
  frameAt(t: number): number;
  clamp(n: number): number;
}

/**
 * How far past a frame's timestamp still counts as that frame, to absorb float/microsecond rounding of
 * media time. Kept well under the shortest frame interval: real files have frames only a clock tick
 * apart (timestamp jitter), and a fixed tolerance would read those as the next frame.
 */
function tolerance(times: Float64Array): number {
  let min = Infinity;
  for (let i = 1; i < times.length; i++) min = Math.min(min, times[i] - times[i - 1]);
  return Math.min(1e-4, Number.isFinite(min) ? min / 4 : 1e-4);
}

function makeClock(times: Float64Array, exact: boolean): FrameClock {
  const n = times.length;
  const last = Math.max(0, n - 1);
  const typical = n > 1 ? times[1] - times[0] : 1 / 30;
  const EPSILON = tolerance(times);
  return {
    frameCount: n,
    exact,
    times,
    clamp: (f) => Math.min(last, Math.max(0, Math.round(f))),
    // Halfway into the frame's display interval: browsers show the last frame whose timestamp is at or
    // before currentTime, so the midpoint is safe from rounding either way. Mirrors
    // `egolabs.ingest.frame_index.seek_time` (tested against real decoded frames in the backend).
    seekTime(f) {
      const i = Math.min(last, Math.max(0, Math.round(f)));
      const next = i + 1 < n ? times[i + 1] : times[i] + (i > 0 ? times[i] - times[i - 1] : typical);
      return (times[i] + next) / 2;
    },
    frameAt(t) {
      let lo = 0;
      let hi = last;
      if (n === 0 || t < times[0] - EPSILON) return 0;
      while (lo < hi) {
        const mid = (lo + hi + 1) >> 1;
        if (times[mid] <= t + EPSILON) lo = mid;
        else hi = mid - 1;
      }
      return lo;
    },
  };
}

export function clockFromIndex(index: FrameIndex): FrameClock {
  const [num, den] = index.time_base;
  const times = new Float64Array(index.frame_count);
  let i = 0;
  for (const [start, step, count] of index.runs) {
    for (let k = 0; k < count && i < times.length; k++) times[i++] = ((start + step * k) * num) / den;
  }
  return makeClock(times, true);
}

export function nominalClock(frameCount: number, fps: number): FrameClock {
  const rate = fps > 0 ? fps : 30;
  const times = new Float64Array(Math.max(0, frameCount));
  for (let i = 0; i < times.length; i++) times[i] = i / rate;
  return makeClock(times, false);
}
