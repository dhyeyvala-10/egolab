"use client";

import { ChevronLeft, ChevronRight, Pause, Play, SkipBack, SkipForward } from "lucide-react";
import { useState, type FormEvent } from "react";
import { formatTimecode } from "@/components/ui";
import { useFrame, type FrameStore } from "@/lib/inspector/frameStore";

const RATES = [0.25, 0.5, 1, 2];

function FrameField({ frameStore, frameCount, onSeek }: { frameStore: FrameStore; frameCount: number; onSeek: (f: number) => void }) {
  const frame = useFrame(frameStore);
  const [draft, setDraft] = useState<string | null>(null);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (draft !== null && draft.trim() !== "") onSeek(Number(draft));
    setDraft(null);
  };
  return (
    <form onSubmit={submit} className="flex items-center gap-1.5">
      <label htmlFor="inspector-frame" className="text-xs text-ink-3">Frame</label>
      <input
        id="inspector-frame"
        data-testid="current-frame"
        data-frame={frame}
        inputMode="numeric"
        className="h-7 w-20 rounded-md border border-line-strong px-2 text-right font-mono text-xs tabular-nums"
        value={draft ?? String(frame)}
        onChange={(e) => setDraft(e.target.value.replace(/[^0-9]/g, ""))}
        onBlur={() => setDraft(null)}
      />
      <span className="font-mono text-xs text-ink-3">/ {Math.max(0, frameCount - 1)}</span>
    </form>
  );
}

function Timecode({ frameStore, fps }: { frameStore: FrameStore; fps: number }) {
  return <span className="font-mono text-xs tabular-nums text-ink-2">{formatTimecode(useFrame(frameStore), fps)}</span>;
}

export function TransportBar({
  playing,
  frameStore,
  frameCount,
  fps,
  rate,
  onRate,
  onToggle,
  onStep,
  onEvent,
  onSeek,
}: {
  playing: boolean;
  frameStore: FrameStore;
  frameCount: number;
  fps: number;
  rate: number;
  onRate: (r: number) => void;
  onToggle: () => void;
  onStep: (delta: number) => void;
  onEvent: (direction: "prev" | "next") => void;
  onSeek: (frame: number) => void;
}) {
  const btn = "grid size-8 place-items-center rounded-md border border-line hover:bg-hover";
  return (
    <div className="flex flex-wrap items-center gap-2">
      <button type="button" className={btn} aria-label="Previous event (Shift+←)" title="Previous event (Shift+←)" onClick={() => onEvent("prev")}>
        <SkipBack className="size-3.5" aria-hidden />
      </button>
      <button type="button" className={btn} aria-label="Previous frame (←)" title="Previous frame (←)" onClick={() => onStep(-1)}>
        <ChevronLeft className="size-4" aria-hidden />
      </button>
      <button type="button" className="grid h-8 w-10 place-items-center rounded-md bg-ink text-canvas" aria-label={playing ? "Pause (Space)" : "Play (Space)"} onClick={onToggle}>
        {playing ? <Pause className="size-4" aria-hidden /> : <Play className="size-4" aria-hidden />}
      </button>
      <button type="button" className={btn} aria-label="Next frame (→)" title="Next frame (→)" onClick={() => onStep(1)}>
        <ChevronRight className="size-4" aria-hidden />
      </button>
      <button type="button" className={btn} aria-label="Next event (Shift+→)" title="Next event (Shift+→)" onClick={() => onEvent("next")}>
        <SkipForward className="size-3.5" aria-hidden />
      </button>
      <FrameField frameStore={frameStore} frameCount={frameCount} onSeek={onSeek} />
      <Timecode frameStore={frameStore} fps={fps} />
      <label className="ml-auto flex items-center gap-1.5 text-xs text-ink-3">
        Speed
        <select className="h-7 rounded-md border border-line-strong px-1.5 text-xs text-ink" value={rate} onChange={(e) => onRate(Number(e.target.value))}>
          {RATES.map((r) => <option key={r} value={r}>{r}×</option>)}
        </select>
      </label>
    </div>
  );
}
