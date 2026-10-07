"use client";

import { usePathname, useRouter } from "next/navigation";
import type { HandTrackRead } from "@/lib/api/types";

export function TrackPicker({ tracks, current }: { tracks: HandTrackRead[]; current: number }) {
  const router = useRouter();
  const pathname = usePathname();
  return (
    <select
      aria-label="Track"
      className="h-[30px] rounded-md border border-line-strong bg-canvas px-2 text-[13px]"
      value={current}
      onChange={(e) => router.push(`${pathname}?track=${e.target.value}`, { scroll: false })}
    >
      {tracks.map((t) => (
        <option key={t.track_id} value={t.track_id}>
          #{t.track_id} · {t.handedness} · {t.frames_detected} frames
        </option>
      ))}
    </select>
  );
}
