"use client";

import { memo, useMemo, type MouseEvent, type ReactNode } from "react";
import { cn } from "@/lib/cn";

/** Frame range [start, end], inclusive. */
export interface TimelineSegment {
  id: string;
  start: number;
  end: number;
  label?: string;
  confidence?: number | null;
  /** Drawn dashed: an annotation being created, not saved yet. */
  pending?: boolean;
  /** Small marker: flagged for review. */
  flagged?: boolean;
}

/** Too many annotations to draw one by one: how many start in [start, end]. */
export interface TimelineBucket {
  start: number;
  end: number;
  count: number;
}

export type TrackKind = "human" | "ai" | "event" | "neutral";

export interface TimelineTrack {
  id: string;
  label: string;
  kind: TrackKind;
  /** Must be sorted by `start`. */
  segments: TimelineSegment[];
  /** Density view, used instead of `segments` when a track is too busy to draw. */
  buckets?: TimelineBucket[] | null;
  /** Count shown next to the label; defaults to the number of segments. */
  total?: number;
  /** Shown in an empty track, e.g. which build phase fills it. */
  emptyHint?: string;
}

export interface TimelineProps {
  tracks: TimelineTrack[];
  frameCount: number;
  fps: number;
  /** Visible frame window. Defaults to the whole video. */
  view?: { start: number; end: number };
  currentFrame?: number;
  onSeek?: (frame: number) => void;
  selectedId?: string | null;
  onSegmentClick?: (segment: TimelineSegment, track: TimelineTrack) => void;
  onBucketClick?: (bucket: TimelineBucket, track: TimelineTrack) => void;
  className?: string;
}

/** Width of the track-label column; overlays positioned over the lanes offset by this. */
export const TIMELINE_LABEL_WIDTH = 140;

const KIND_CLASSES: Record<TrackKind, string> = {
  human: "bg-human-bg border-human-line text-human",
  ai: "bg-ai-bg border-ai-line text-ai",
  event: "bg-running-bg border-running-line text-running",
  neutral: "bg-hover border-line-strong text-ink-2",
};

const BUCKET_CLASSES: Record<TrackKind, string> = {
  human: "bg-human",
  ai: "bg-ai",
  event: "bg-running",
  neutral: "bg-ink-3",
};

/** Frame → `MM:SS:FF` (or `H:MM:SS:FF` past an hour). */
export function formatTimecode(frame: number, fps: number): string {
  const f = Math.max(0, Math.round(frame));
  const rate = Math.max(1, Math.round(fps));
  const totalSeconds = Math.floor(f / rate);
  const ff = f % rate;
  const s = totalSeconds % 60;
  const m = Math.floor(totalSeconds / 60) % 60;
  const h = Math.floor(totalSeconds / 3600);
  const pad = (n: number) => String(n).padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}:${pad(ff)}` : `${pad(m)}:${pad(s)}:${pad(ff)}`;
}

/** First index whose segment starts at or after `frame`. */
function lowerBound(segments: TimelineSegment[], frame: number): number {
  let lo = 0;
  let hi = segments.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (segments[mid].start < frame) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/**
 * Segments intersecting [viewStart, viewEnd]. Uses binary search on the sorted starts, offset by the
 * track's longest segment, so a 30-minute video with many events only touches what is on screen.
 */
export function visibleSegments(
  segments: TimelineSegment[],
  viewStart: number,
  viewEnd: number,
  maxLength = segments.reduce((m, s) => Math.max(m, s.end - s.start), 0),
): TimelineSegment[] {
  const out: TimelineSegment[] = [];
  for (let i = lowerBound(segments, viewStart - maxLength); i < segments.length; i++) {
    const s = segments[i];
    if (s.start > viewEnd) break;
    if (s.end >= viewStart) out.push(s);
  }
  return out;
}

const TICK_SECONDS = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600];

function ticks(viewStart: number, viewEnd: number, fps: number, target = 8): number[] {
  const spanSeconds = (viewEnd - viewStart + 1) / fps;
  if (spanSeconds < 2) {
    // Zoomed in to individual frames: tick every few frames.
    const step = [1, 2, 5, 10, 15, 30].find((s) => (viewEnd - viewStart + 1) / s <= target) ?? 30;
    const out: number[] = [];
    for (let f = Math.ceil(viewStart / step) * step; f <= viewEnd; f += step) out.push(f);
    return out;
  }
  const step = (TICK_SECONDS.find((t) => spanSeconds / t <= target) ?? 3600) * fps;
  const out: number[] = [];
  for (let f = Math.ceil(viewStart / step) * step; f <= viewEnd; f += step) out.push(Math.round(f));
  return out;
}

function seekHandler(onSeek: ((frame: number) => void) | undefined, vs: number, ve: number) {
  return (e: MouseEvent<HTMLDivElement>) => {
    if (!onSeek) return;
    const rect = e.currentTarget.getBoundingClientRect();
    if (rect.width <= 0) return;
    const ratio = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
    onSeek(Math.min(ve, vs + Math.floor(ratio * (ve - vs + 1))));
  };
}

interface TrackRowProps {
  track: TimelineTrack;
  vs: number;
  ve: number;
  maxLength: number;
  selectedId?: string | null;
  onSeek?: (frame: number) => void;
  onSegmentClick?: TimelineProps["onSegmentClick"];
  onBucketClick?: TimelineProps["onBucketClick"];
}

/** One track. Memoised so moving the playhead every frame doesn't re-render the segments. */
const TrackRow = memo(function TrackRow({ track, vs, ve, maxLength, selectedId, onSeek, onSegmentClick, onBucketClick }: TrackRowProps) {
  const span = ve - vs + 1;
  const pos = (frame: number) => ((frame - vs) / span) * 100;
  const segs = track.buckets ? [] : visibleSegments(track.segments, vs, ve, maxLength);
  const maxCount = track.buckets?.reduce((m, b) => Math.max(m, b.count), 0) ?? 0;
  const total = track.total ?? track.segments.filter((s) => !s.pending).length;
  const empty = total === 0 && !track.segments.length;

  return (
    <div className="contents">
      <div className="flex h-8 items-center justify-between gap-2 border-b border-r border-line px-3">
        <span className="truncate text-xs font-medium">{track.label}</span>
        <span className="font-mono text-[10px] tabular-nums text-ink-3">{total || ""}</span>
      </div>
      <div className="relative h-8 cursor-pointer overflow-hidden border-b border-line" onClick={seekHandler(onSeek, vs, ve)} data-testid={`track-${track.id}`}>
        {empty && track.emptyHint ? (
          <span className="pointer-events-none absolute inset-y-0 left-2 flex items-center text-[11px] text-ink-3">{track.emptyHint}</span>
        ) : null}
        {track.buckets?.map((b) => {
          const left = Math.max(0, pos(b.start));
          const right = Math.min(100, pos(b.end + 1));
          return (
            <div
              key={b.start}
              data-bucket={b.start}
              title={`${b.count.toLocaleString("en-US")} annotations · f${b.start}–f${b.end}`}
              onClick={
                onBucketClick
                  ? (e) => {
                      e.stopPropagation();
                      onBucketClick(b, track);
                    }
                  : undefined
              }
              className={cn("absolute bottom-1.5 rounded-[1px]", BUCKET_CLASSES[track.kind])}
              style={{
                left: `${left}%`,
                width: `max(1px, ${Math.max(0, right - left)}%)`,
                height: `${4 + 16 * (maxCount ? b.count / maxCount : 0)}px`,
                opacity: 0.35 + 0.65 * (maxCount ? b.count / maxCount : 0),
              }}
            />
          );
        })}
        {segs.map((s) => {
          const left = Math.max(0, pos(s.start));
          const right = Math.min(100, pos(s.end + 1));
          const selected = selectedId === s.id;
          return (
            <div
              key={s.id}
              data-segment={s.id}
              data-selected={selected || undefined}
              title={`${s.label ?? track.label} · f${s.start}–f${s.end}${s.confidence != null ? ` · ${s.confidence.toFixed(2)}` : ""}`}
              onClick={
                onSegmentClick
                  ? (e) => {
                      e.stopPropagation();
                      onSegmentClick(s, track);
                    }
                  : undefined
              }
              className={cn(
                "absolute top-1.5 bottom-1.5 min-w-[2px] overflow-hidden rounded-sm border px-1 text-[10px] leading-[18px] whitespace-nowrap",
                KIND_CLASSES[track.kind],
                s.pending && "border-dashed",
                selected && "z-10 border-ink ring-1 ring-ink",
              )}
              style={{ left: `${left}%`, width: `${Math.max(0, right - left)}%` }}
            >
              {s.flagged ? <span className="mr-1 inline-block size-1.5 rounded-full bg-warning align-middle" aria-label="Needs review" /> : null}
              {s.label}
            </div>
          );
        })}
      </div>
    </div>
  );
});

/** Vertical line at `frame`, drawn over the lanes. Render inside the Timeline's `overlay`. */
export function TimelinePlayhead({ frame, view }: { frame: number; view: { start: number; end: number } }) {
  if (frame < view.start || frame > view.end) return null;
  const ratio = (frame - view.start) / (view.end - view.start + 1);
  return (
    <div
      aria-hidden
      data-testid="timeline-playhead"
      className="pointer-events-none absolute inset-y-0 z-20 w-px bg-ink"
      style={{ left: `calc(${TIMELINE_LABEL_WIDTH}px + (100% - ${TIMELINE_LABEL_WIDTH}px) * ${ratio})` }}
    />
  );
}

export function Timeline({
  tracks,
  frameCount,
  fps,
  view,
  currentFrame,
  onSeek,
  selectedId,
  onSegmentClick,
  onBucketClick,
  className,
  overlay,
  header,
}: TimelineProps & {
  /** Drawn over the lanes (e.g. a playhead that updates without re-rendering the tracks). */
  overlay?: ReactNode;
  /** Replaces the current-frame readout in the top-left cell. */
  header?: ReactNode;
}) {
  const lastFrame = Math.max(0, frameCount - 1);
  const vs = Math.max(0, view?.start ?? 0);
  const ve = Math.min(lastFrame, view?.end ?? lastFrame);
  const span = ve - vs + 1; // frames in view
  const pos = (frame: number) => ((frame - vs) / span) * 100;

  const maxLengths = useMemo(
    () => new Map(tracks.map((t) => [t.id, t.segments.reduce((m, s) => Math.max(m, s.end - s.start), 0)])),
    [tracks],
  );
  const tickFrames = useMemo(() => ticks(vs, ve, fps), [vs, ve, fps]);
  const zoomedToFrames = span / fps < 2;

  return (
    <div className={cn("min-w-0 rounded-lg border border-line bg-canvas", className)}>
      <div className="relative grid" style={{ gridTemplateColumns: `${TIMELINE_LABEL_WIDTH}px minmax(0,1fr)` }}>
        <div className="flex h-7 items-center border-b border-r border-line px-3 font-mono text-[11px] tabular-nums text-ink-2">
          {header ?? (currentFrame != null ? `${formatTimecode(currentFrame, fps)} · f${currentFrame}` : formatTimecode(vs, fps))}
        </div>
        <div className="relative h-7 cursor-pointer overflow-hidden border-b border-line" onClick={seekHandler(onSeek, vs, ve)} data-testid="timeline-ruler">
          {tickFrames.map((f) => (
            <div key={f} className="absolute inset-y-0 border-l border-line" style={{ left: `${pos(f)}%` }}>
              <span className="absolute left-1 top-1.5 whitespace-nowrap font-mono text-[10px] text-ink-3">
                {zoomedToFrames ? `f${f}` : formatTimecode(f, fps).slice(0, -3)}
              </span>
            </div>
          ))}
        </div>

        {tracks.map((track) => (
          <TrackRow
            key={track.id}
            track={track}
            vs={vs}
            ve={ve}
            maxLength={maxLengths.get(track.id) ?? 0}
            selectedId={selectedId}
            onSeek={onSeek}
            onSegmentClick={onSegmentClick}
            onBucketClick={onBucketClick}
          />
        ))}

        {currentFrame != null ? <TimelinePlayhead frame={currentFrame} view={{ start: vs, end: ve }} /> : null}
        {overlay}
      </div>
    </div>
  );
}
