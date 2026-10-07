"use client";

import { Maximize2, ZoomIn, ZoomOut } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { formatTimecode, Timeline, TimelinePlayhead, type TimelineBucket, type TimelineSegment, type TimelineTrack } from "@/components/ui";
import { browserApi } from "@/lib/api/browser";
import type { TimelineRead } from "@/lib/api/types";
import { useFrame, type FrameStore } from "@/lib/inspector/frameStore";
import { MIN_SPAN, panView, zoomView, type View } from "@/lib/inspector/view";

function LivePlayhead({ frameStore, view }: { frameStore: FrameStore; view: View }) {
  return <TimelinePlayhead frame={useFrame(frameStore)} view={view} />;
}

function LiveTimecode({ frameStore, fps }: { frameStore: FrameStore; fps: number }) {
  const frame = useFrame(frameStore);
  return (
    <span>
      {formatTimecode(frame, fps)} · f{frame}
    </span>
  );
}

/** The whole video, with the visible window as a draggable thumb. */
function Overview({ frameCount, view, onViewChange, frameStore }: { frameCount: number; view: View; onViewChange: (v: View) => void; frameStore: FrameStore }) {
  const bar = useRef<HTMLDivElement>(null);
  const drag = useRef<{ x: number; start: number } | null>(null);
  const frame = useFrame(frameStore);
  const span = view.end - view.start + 1;
  const toFrames = (px: number) => (px / (bar.current?.clientWidth || 1)) * frameCount;
  const down = (e: ReactPointerEvent<HTMLDivElement>) => {
    e.currentTarget.setPointerCapture(e.pointerId);
    const rect = bar.current!.getBoundingClientRect();
    const at = toFrames(e.clientX - rect.left);
    // Grab the thumb where it is, or jump it so its centre is under the pointer.
    const start = at >= view.start && at <= view.end ? view.start : Math.round(at - span / 2);
    drag.current = { x: e.clientX, start };
    onViewChange(panView({ start, end: start + span - 1 }, 0, frameCount));
  };
  const move = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    const start = drag.current.start + Math.round(toFrames(e.clientX - drag.current.x));
    onViewChange(panView({ start, end: start + span - 1 }, 0, frameCount));
  };
  return (
    <div
      ref={bar}
      data-testid="timeline-overview"
      className="relative h-4 cursor-grab touch-none rounded-sm border border-line bg-subtle"
      onPointerDown={down}
      onPointerMove={move}
      onPointerUp={() => (drag.current = null)}
    >
      <div
        className="absolute inset-y-0 rounded-sm border border-ink-3 bg-hover"
        style={{ left: `${(view.start / frameCount) * 100}%`, width: `max(4px, ${(span / frameCount) * 100}%)` }}
      />
      <div className="pointer-events-none absolute inset-y-0 w-px bg-ink" style={{ left: `${(frame / frameCount) * 100}%` }} />
    </div>
  );
}

const PHASE_HINT = (phase: number | null | undefined) => (phase ? `Filled from Phase ${phase}` : undefined);

export function InspectorTimeline({
  videoId,
  frameCount,
  fps,
  view,
  onViewChange,
  frameStore,
  onSeek,
  selectedId,
  onSelect,
  version,
  pending,
  canEdit,
}: {
  videoId: string;
  frameCount: number;
  fps: number;
  view: View;
  onViewChange: (v: View) => void;
  frameStore: FrameStore;
  onSeek: (frame: number) => void;
  selectedId: string | null;
  onSelect: (id: string) => void;
  version: number;
  /** The annotation being created, drawn dashed on the human track. */
  pending: { start: number; end: number } | null;
  canEdit: boolean;
}) {
  const [data, setData] = useState<TimelineRead | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const lanes = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(900);

  useEffect(() => {
    const el = lanes.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Fetch what the tracks draw for the visible window. Debounced so zooming doesn't flood the API.
  const buckets = Math.max(50, Math.min(1000, Math.round(width / 3)));
  useEffect(() => {
    const ctrl = new AbortController();
    const timer = setTimeout(async () => {
      setLoading(true);
      try {
        const res = await browserApi<TimelineRead>(`/videos/${videoId}/timeline`, {
          query: { frame_from: view.start, frame_to: view.end, buckets },
          signal: ctrl.signal,
        });
        if (res.ok) {
          setData(res.data);
          setError(null);
        } else setError(res.message);
      } catch {
        return; // aborted by a newer request
      } finally {
        if (!ctrl.signal.aborted) setLoading(false);
      }
    }, 90);
    return () => {
      clearTimeout(timer);
      ctrl.abort();
    };
  }, [videoId, view.start, view.end, buckets, version]);

  const tracks: TimelineTrack[] = useMemo(() => {
    if (!data) return [];
    return data.tracks.map((t) => {
      const segments: TimelineSegment[] = (t.segments ?? []).map((s) => ({
        id: s.id,
        start: s.start,
        end: s.end,
        label: s.label,
        confidence: s.confidence,
        flagged: s.needs_review,
      }));
      if (t.id === "human" && pending) {
        const seg = { id: "draft", start: Math.min(pending.start, pending.end), end: Math.max(pending.start, pending.end), label: "New", pending: true };
        const at = segments.findIndex((s) => s.start > seg.start);
        segments.splice(at < 0 ? segments.length : at, 0, seg);
      }
      const hint =
        t.id === "human"
          ? canEdit
            ? "No annotations here yet — press A to add one"
            : "No annotations here yet"
          : (PHASE_HINT(t.filled_from_phase) ?? "Nothing detected here");
      return { id: t.id, label: t.label, kind: t.kind, segments, buckets: t.buckets, total: t.total, emptyHint: hint };
    });
  }, [data, pending, canEdit]);

  const onSegmentClick = useCallback((s: TimelineSegment) => s.id !== "draft" && onSelect(s.id), [onSelect]);
  const onBucketClick = useCallback(
    (b: TimelineBucket) => onViewChange(zoomView({ start: b.start, end: Math.max(b.end, b.start + MIN_SPAN - 1) }, 1, b.start, frameCount)),
    [frameCount, onViewChange],
  );

  // Wheel: vertical zooms around the pointer, horizontal (or Shift) pans. Native listener so it can
  // prevent the page from scrolling.
  const viewRef = useRef(view);
  useEffect(() => {
    viewRef.current = view;
  }, [view]);
  useEffect(() => {
    const el = lanes.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      const v = viewRef.current;
      const rect = el.getBoundingClientRect();
      const laneLeft = rect.left + 140;
      const laneWidth = Math.max(1, rect.width - 140);
      const span = v.end - v.start + 1;
      if (e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY)) {
        e.preventDefault();
        const delta = e.shiftKey ? e.deltaY || e.deltaX : e.deltaX;
        onViewChange(panView(v, Math.round((delta / laneWidth) * span), frameCount));
        return;
      }
      if (e.clientX < laneLeft) return; // over the labels: let the page scroll
      e.preventDefault();
      const anchor = v.start + ((e.clientX - laneLeft) / laneWidth) * span;
      onViewChange(zoomView(v, Math.exp(e.deltaY * 0.0015), anchor, frameCount));
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [frameCount, onViewChange]);

  const span = view.end - view.start + 1;
  const zoomBy = (factor: number) => onViewChange(zoomView(view, factor, frameStore.get(), frameCount));

  return (
    <div className="flex flex-col gap-2" data-testid="inspector-timeline">
      <div className="flex flex-wrap items-center gap-2 text-xs text-ink-2">
        <div className="flex items-center gap-1">
          <button type="button" aria-label="Zoom out" onClick={() => zoomBy(2)} className="grid size-7 place-items-center rounded-md border border-line hover:bg-hover">
            <ZoomOut className="size-3.5" aria-hidden />
          </button>
          <button type="button" aria-label="Zoom in" onClick={() => zoomBy(0.5)} className="grid size-7 place-items-center rounded-md border border-line hover:bg-hover">
            <ZoomIn className="size-3.5" aria-hidden />
          </button>
          <button
            type="button"
            aria-label="Show the whole video"
            onClick={() => onViewChange({ start: 0, end: frameCount - 1 })}
            className="grid size-7 place-items-center rounded-md border border-line hover:bg-hover"
          >
            <Maximize2 className="size-3.5" aria-hidden />
          </button>
        </div>
        <span className="font-mono tabular-nums" data-testid="timeline-view">
          f{view.start}–f{view.end} · {(span / fps).toFixed(span / fps < 10 ? 2 : 0)} s
        </span>
        <span className="text-ink-3">Scroll to zoom · Shift+scroll to pan</span>
        {loading ? <span className="text-ink-3">Loading…</span> : null}
        {error ? <span className="text-error">{error}</span> : null}
      </div>
      <Overview frameCount={frameCount} view={view} onViewChange={onViewChange} frameStore={frameStore} />
      <div ref={lanes}>
        <Timeline
          tracks={tracks}
          frameCount={frameCount}
          fps={fps}
          view={view}
          onSeek={onSeek}
          selectedId={selectedId}
          onSegmentClick={onSegmentClick}
          onBucketClick={onBucketClick}
          header={<LiveTimecode frameStore={frameStore} fps={fps} />}
          overlay={<LivePlayhead frameStore={frameStore} view={view} />}
        />
      </div>
    </div>
  );
}
