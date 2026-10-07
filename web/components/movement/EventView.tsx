"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { RunPlayer } from "@/components/cv/RunPlayer";
import { Timeline, TimelinePlayhead, type TimelineTrack } from "@/components/ui";
import { browserApi } from "@/lib/api/browser";
import type { EventEvidenceFrames, EvidenceFrame, MovementEventDetail, VideoDetail } from "@/lib/api/types";
import { frameRuns, measurementLabel } from "@/lib/cv/evidence";
import { createFrameStore, useFrame, type FrameStore } from "@/lib/inspector/frameStore";
import { cn } from "@/lib/cn";
import { EvidenceCharts } from "./EvidenceCharts";

const PAGE = 300;

function Playhead({ frameStore, view }: { frameStore: FrameStore; view: { start: number; end: number } }) {
  return <TimelinePlayhead frame={useFrame(frameStore)} view={view} />;
}

function CurrentRow({ frameStore, frame }: { frameStore: FrameStore; frame: number }) {
  return useFrame(frameStore) === frame ? <span className="sr-only">(shown)</span> : null;
}

/**
 * The event in the player (its hand's skeleton, its object's box), its evidence frames on a timeline, the
 * measurements the rule compared, and the keypoint rows themselves — read back from the hand-tracking run.
 */
export function EventView({ event, video }: { event: MovementEventDetail; video: VideoDetail }) {
  const [frameStore] = useState(() => createFrameStore(event.start_frame));
  const seekRef = useRef<((frame: number) => void) | null>(null);
  const seek = (f: number) => seekRef.current?.(f);
  const ev = event.evidence;
  const [rows, setRows] = useState<EvidenceFrame[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = (offset: number) =>
    browserApi<EventEvidenceFrames>(`/movement/events/${event.id}/evidence`, { query: { offset, limit: PAGE } })
      .then((res) => {
        if (!res.ok) return setError(res.message);
        setRows((r) => (offset ? [...r, ...res.data.frames] : res.data.frames));
        setTotal(res.data.total);
      })
      .catch(() => undefined);
  useEffect(() => {
    void load(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [event.id]);

  // A window around the event, so short events are wide enough to see.
  const frameCount = video.frame_count ?? event.end_frame + 1;
  const span = event.end_frame - event.start_frame + 1;
  const view = useMemo(() => {
    const margin = Math.max(30, span);
    return { start: Math.max(0, event.start_frame - margin), end: Math.min(frameCount - 1, event.end_frame + margin) };
  }, [event.start_frame, event.end_frame, span, frameCount]);
  const tracks: TimelineTrack[] = useMemo(
    () => [
      { id: "event", label: event.label, kind: "ai", total: 1, segments: [{ id: "event", start: event.start_frame, end: event.end_frame, label: `${span} frames`, confidence: event.confidence }] },
      {
        id: "evidence",
        label: "Evidence frames",
        kind: "neutral",
        total: ev.frame_count,
        segments: frameRuns(ev.frames).map(([a, b]) => ({ id: `e${a}`, start: a, end: b })),
      },
    ],
    [event, ev, span],
  );
  const measures = Object.keys(ev.measurements);

  return (
    <div className="flex flex-col gap-4">
      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <RunPlayer video={video} runId={event.hand_run_id} objectRunId={event.object_run_id} highlightObject={event.object_track_id}
                   startFrame={event.start_frame} frameStore={frameStore} seekRef={seekRef} />
        <div className="flex flex-col gap-3">
          <ol className="flex flex-wrap items-center gap-1.5 text-xs" aria-label="Interaction">
            {[
              `${event.handedness === "left" ? "Left" : "Right"} hand #${event.hand_track_id}`,
              event.fingers.length ? event.fingers.join(", ") : "whole hand",
              event.movement_class.label,
              event.object_label ? `${event.object_label} #${event.object_track_id}` : "no object",
              `${event.start_s.toFixed(2)}–${event.end_s.toFixed(2)} s`,
            ].map((step, i) => (
              <li key={i} className="flex items-center gap-1.5">
                {i ? <span aria-hidden className="text-ink-3">→</span> : null}
                <span className={cn("rounded-md border px-2 py-0.5", i === 2 ? "border-ai-line bg-ai-bg font-semibold text-ink" : "border-line bg-canvas text-ink-2")}>{step}</span>
              </li>
            ))}
          </ol>
          <div className="rounded-md border border-line bg-subtle px-3 py-2 text-xs">
            <div className="font-semibold text-ink">Rule</div>
            <p className="mt-0.5 text-ink-2">{ev.rule || "—"}</p>
            {Object.keys(ev.thresholds).length ? (
              <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 font-mono text-[11px]">
                {Object.entries(ev.thresholds).map(([k, v]) => (
                  <div key={k} className="contents"><dt className="text-ink-3">{k}</dt><dd className="tabular-nums text-ink">{Number(v).toFixed(3).replace(/\.?0+$/, "")}</dd></div>
                ))}
              </dl>
            ) : null}
          </div>
          <div className="flex flex-wrap gap-2 text-xs">
            <button type="button" onClick={() => seek(event.start_frame)} className="h-7 rounded-md border border-line-strong px-2.5 font-medium hover:bg-hover">Go to start (f{event.start_frame})</button>
            <button type="button" onClick={() => seek(event.end_frame)} className="h-7 rounded-md border border-line-strong px-2.5 font-medium hover:bg-hover">Go to end (f{event.end_frame})</button>
          </div>
        </div>
      </div>
      <Timeline tracks={tracks} frameCount={frameCount} fps={video.fps ?? 30} view={view} onSeek={seek} onSegmentClick={(s) => seek(s.start)}
                overlay={<Playhead frameStore={frameStore} view={view} />} />
      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold">Measurements</h2>
        <EvidenceCharts className={event.movement_class.name} frames={ev.frames} measurements={ev.measurements} thresholds={ev.thresholds} onPick={seek} />
      </section>
      <section className="flex flex-col gap-2">
        <div className="flex items-baseline justify-between gap-2">
          <h2 className="text-sm font-semibold">Keypoint frames</h2>
          <span className="text-xs text-ink-3">
            Rows of hand-tracking run <span className="font-mono">{event.hand_run_id.slice(0, 8)}</span>, track #{ev.track_id} · {ev.parts.length} Parquet part{ev.parts.length === 1 ? "" : "s"}
          </span>
        </div>
        {error ? <p className="text-xs text-error">{error}</p> : null}
        <div className="max-h-96 overflow-auto rounded-md border border-line" data-testid="evidence-frames">
          <table className="w-full border-collapse text-xs">
            <thead className="sticky top-0 bg-subtle">
              <tr>
                <th className="px-2 py-1.5 text-left font-semibold text-ink-3">Frame</th>
                <th className="px-2 py-1.5 text-left font-semibold text-ink-3">Time</th>
                <th className="px-2 py-1.5 text-right font-semibold text-ink-3">Keypoints</th>
                <th className="px-2 py-1.5 text-right font-semibold text-ink-3">Hand confidence</th>
                {measures.map((m) => <th key={m} className="px-2 py-1.5 text-right font-semibold text-ink-3">{measurementLabel(m)}</th>)}
                <th className="px-2 py-1.5 text-left font-semibold text-ink-3">Object box</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.frame} className="cursor-pointer border-t border-line hover:bg-hover" onClick={() => seek(r.frame)} data-frame={r.frame}>
                  <td className="px-2 py-1 font-mono tabular-nums">f{r.frame} <CurrentRow frameStore={frameStore} frame={r.frame} /></td>
                  <td className="px-2 py-1 font-mono tabular-nums">{r.timestamp_s.toFixed(3)} s</td>
                  <td className="px-2 py-1 text-right tabular-nums">{r.keypoints.length}</td>
                  <td className="px-2 py-1 text-right tabular-nums">{r.confidence.toFixed(2)}</td>
                  {measures.map((m) => <td key={m} className="px-2 py-1 text-right tabular-nums">{r.values[m] != null ? Number(r.values[m]).toFixed(3) : "—"}</td>)}
                  <td className="px-2 py-1 font-mono text-[11px] text-ink-2">{r.object_bbox ? r.object_bbox.map((v) => v.toFixed(3)).join(", ") : "—"}</td>
                </tr>
              ))}
              {total === null && !error ? <tr><td colSpan={5 + measures.length} className="px-2 py-3 text-ink-3">Reading the keypoints…</td></tr> : null}
            </tbody>
          </table>
        </div>
        {total != null && rows.length < total ? (
          <button type="button" onClick={() => void load(rows.length)} className="h-7 self-start rounded-md border border-line-strong px-2.5 text-xs font-medium hover:bg-hover">
            Show more ({rows.length} of {total})
          </button>
        ) : null}
      </section>
    </div>
  );
}
