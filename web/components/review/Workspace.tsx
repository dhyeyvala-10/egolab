"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { RunPlayer } from "@/components/cv/RunPlayer";
import { ConfidenceBadge, SourceBadge, StatusBadge } from "@/components/ui";
import { browserApi } from "@/lib/api/browser";
import type {
  BulkPreview,
  CorrectionResult,
  MovementClassRead,
  MovementEventDetail,
  QueuePage,
  ReviewBatchRead,
  ReviewItem,
  VideoDetail,
} from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { frameRuns } from "@/lib/cv/evidence";
import { createFrameStore, useFrame, type FrameStore } from "@/lib/inspector/frameStore";
import { bulkFilters, queueQuery, REVIEW_KEYS, reviewKey, type WorkspaceQuery } from "@/lib/review";
import { CorrectForm, type CorrectionBody } from "./CorrectForm";

type Status = "confirmed" | "rejected" | "needs_review" | "auto_detected";
interface Toast {
  text: string;
  undo?: () => Promise<void>;
  href?: string;
}

const VERB: Record<Status, string> = { confirmed: "Accepted", rejected: "Rejected", needs_review: "Flagged", auto_detected: "Reopened" };

function span(i: { start_frame: number; end_frame: number }): string {
  return `f${i.start_frame}–f${i.end_frame}`;
}

/** Keeps the player inside the event while looping: past the end, back to the start. */
function Loop({ frameStore, seekRef, start, end, on }: { frameStore: FrameStore; seekRef: React.RefObject<((f: number) => void) | null>; start: number; end: number; on: boolean }) {
  const frame = useFrame(frameStore);
  useEffect(() => {
    if (on && (frame > end + 2 || frame < start - 30)) seekRef.current?.(start);
  }, [frame, on, start, end, seekRef]);
  return null;
}

function EvidenceStrip({ event, seek, frameStore }: { event: MovementEventDetail; seek: (f: number) => void; frameStore: FrameStore }) {
  const frame = useFrame(frameStore);
  const runs = frameRuns(event.evidence.frames);
  const lo = Math.min(event.start_frame, event.evidence.frames[0] ?? event.start_frame);
  const hi = Math.max(event.end_frame, event.evidence.frames.at(-1) ?? event.end_frame);
  const w = Math.max(1, hi - lo + 1);
  return (
    <div className="flex flex-col gap-1.5" data-testid="evidence-strip">
      <div className="flex items-baseline justify-between text-xs">
        <span className="font-semibold">Evidence frames</span>
        <span className="text-ink-3 tabular-nums">{event.evidence.frame_count} keypoint frames</span>
      </div>
      <div className="relative h-5 rounded border border-line bg-subtle" aria-hidden>
        {runs.map(([a, b]) => (
          <span key={a} className="absolute inset-y-1 rounded-sm bg-ai/70" style={{ left: `${((a - lo) / w) * 100}%`, width: `max(2px, ${((b - a + 1) / w) * 100}%)` }} />
        ))}
        {frame >= lo && frame <= hi ? <span className="absolute inset-y-0 w-[2px] bg-ink" style={{ left: `${((frame - lo) / w) * 100}%` }} /> : null}
      </div>
      <div className="flex flex-wrap gap-1">
        {runs.slice(0, 12).map(([a, b]) => (
          <button key={a} type="button" onClick={() => seek(a)} className="h-6 rounded border border-line px-1.5 font-mono text-[11px] hover:bg-hover">
            f{a}{b > a ? `–${b}` : ""}
          </button>
        ))}
        {runs.length > 12 ? <span className="self-center text-[11px] text-ink-3">+{runs.length - 12} more</span> : null}
      </div>
    </div>
  );
}

/** The current event: its clip looping in the player with skeleton and object box, and why it is here. */
function Stage({ item, event, video, loop }: { item: ReviewItem; event: MovementEventDetail; video: VideoDetail; loop: boolean }) {
  const [frameStore] = useState(() => createFrameStore(event.start_frame));
  const seekRef = useRef<((frame: number) => void) | null>(null);
  const seek = (f: number) => seekRef.current?.(f);
  const parts = item.priority_parts;
  return (
    <div className="flex flex-col gap-3">
      <RunPlayer video={video} runId={event.hand_run_id} objectRunId={event.object_run_id} highlightObject={event.object_track_id}
                 startFrame={event.start_frame} frameStore={frameStore} seekRef={seekRef} />
      <Loop frameStore={frameStore} seekRef={seekRef} start={event.start_frame} end={event.end_frame} on={loop} />
      <EvidenceStrip event={event} seek={seek} frameStore={frameStore} />
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-4" aria-label="Why this is in the queue">
        <div><dt className="text-ink-3">Priority</dt><dd className="font-mono tabular-nums">{item.priority.toFixed(3)}</dd></div>
        <div><dt className="text-ink-3">Low confidence</dt><dd className="font-mono tabular-nums">+{parts.confidence.toFixed(3)}</dd></div>
        <div><dt className="text-ink-3">Disagreement</dt><dd className="font-mono tabular-nums">{item.disagreement == null ? "no other model yet" : `+${parts.disagreement.toFixed(3)} (${item.disagreement.toFixed(2)} vs ${item.compared_versions})`}</dd></div>
        <div><dt className="text-ink-3">Class rarity</dt><dd className="font-mono tabular-nums">+{parts.rarity.toFixed(3)}</dd></div>
      </dl>
    </div>
  );
}

/**
 * A review workspace: one event at a time from the active-learning queue (its clip loops with the skeleton
 * and object box), accept / reject / correct from the keyboard, and the queue beside it for bulk review.
 */
export function Workspace({ initial, query, classes, lead, scope }: {
  initial: QueuePage;
  query: WorkspaceQuery;
  classes: MovementClassRead[];
  lead: boolean;
  scope: string;
}) {
  const [items, setItems] = useState<ReviewItem[]>(initial.items);
  const [total, setTotal] = useState(initial.total);
  const [index, setIndex] = useState(0);
  const [skipped, setSkipped] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [event, setEvent] = useState<MovementEventDetail | null>(null);
  const [videos, setVideos] = useState<Record<string, VideoDetail>>({});
  const [correcting, setCorrecting] = useState(false);
  const [loop, setLoop] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<Toast | null>(null);
  const [reviewed, setReviewed] = useState(0);
  const [preview, setPreview] = useState<{ action: "confirmed" | "rejected"; data: BulkPreview } | null>(null);
  const current = items[index] ?? null;
  const q = useMemo(() => queueQuery(query), [query]);

  const refresh = useCallback(async (keep?: string) => {
    const res = await browserApi<QueuePage>("/review/queue", { query: { ...q, limit: 50 } });
    if (!res.ok) return setError(res.message);
    const fresh = res.data.items.filter((i) => !skipped.has(i.id));
    const later = res.data.items.filter((i) => skipped.has(i.id));
    const next = [...fresh, ...later];
    setItems(next);
    setTotal(res.data.total);
    const at = keep ? next.findIndex((i) => i.id === keep) : -1;
    setIndex(at >= 0 ? at : 0);
    setSelected(new Set());
  }, [q, skipped]);

  // The current event's detail and video.
  useEffect(() => {
    if (!current) return setEvent(null);
    let live = true;
    setEvent(null);
    setCorrecting(false);
    void browserApi<MovementEventDetail>(`/movement/events/${current.id}`).then((res) => {
      if (!live) return;
      if (res.ok) setEvent(res.data);
      else setError(res.message);
    });
    if (!videos[current.video.id]) {
      void browserApi<VideoDetail>(`/videos/${current.video.id}`).then((res) => {
        if (live && res.ok) setVideos((v) => ({ ...v, [res.data.id]: res.data }));
      });
    }
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current?.id]);

  const drop = useCallback((id: string) => {
    setItems((xs) => {
      const at = xs.findIndex((x) => x.id === id);
      const next = xs.filter((x) => x.id !== id);
      setIndex((i) => Math.min(at >= 0 && at < i ? i - 1 : i, Math.max(0, next.length - 1)));
      if (next.length < 5) setTimeout(() => void refresh(), 0);
      return next;
    });
    setTotal((t) => Math.max(0, t - 1));
  }, [refresh]);

  const setStatus = useCallback(async (status: Status) => {
    if (!current || busy) return;
    setBusy(true);
    setError(null);
    const item = current;
    const res = await browserApi<CorrectionResult>(`/review/events/${item.id}/status`, { method: "POST", body: { status } });
    setBusy(false);
    if (!res.ok) return setError(res.message);
    setReviewed((n) => n + 1);
    if (status === "needs_review") {
      setItems((xs) => xs.map((x) => (x.id === item.id ? { ...x, status } : x)));
      setIndex((i) => Math.min(i + 1, items.length - 1));
    } else drop(item.id);
    setToast({
      text: `${VERB[status]} ${item.movement_class.label} ${span(item)}`,
      undo: async () => {
        const back = await browserApi(`/review/events/${item.id}/status`, { method: "POST", body: { status: item.status } });
        if (!back.ok) return setError(back.message);
        setToast(null);
        setReviewed((n) => Math.max(0, n - 1));
        await refresh(item.id);
      },
    });
  }, [current, busy, drop, refresh, items.length]);

  const correct = useCallback(async (body: CorrectionBody): Promise<string | null> => {
    if (!current) return null;
    const item = current;
    const res = await browserApi<CorrectionResult>(`/review/events/${item.id}/correct`, { method: "POST", body });
    if (!res.ok) return res.message;
    setReviewed((n) => n + 1);
    drop(item.id);
    setToast({ text: `Corrected ${item.movement_class.label} → ${res.data.event.movement_class.label} ${span(res.data.event)}`, href: `/cv/movements/events/${res.data.event.id}` });
    return null;
  }, [current, drop]);

  const skip = useCallback((d: 1 | -1) => {
    if (!current) return;
    if (d === 1) setSkipped((s) => new Set(s).add(current.id));
    setIndex((i) => Math.max(0, Math.min(items.length - 1, i + d)));
  }, [current, items.length]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (correcting) {
        if (e.key === "Escape") setCorrecting(false);
        return;
      }
      const k = reviewKey(e);
      if (!k || !current || preview) return;
      e.preventDefault();
      if (k === "accept") void setStatus("confirmed");
      else if (k === "reject") void setStatus("rejected");
      else if (k === "flag") void setStatus("needs_review");
      else if (k === "correct") setCorrecting(true);
      else if (k === "next") skip(1);
      else if (k === "prev") skip(-1);
      else if (k === "loop") setLoop((l) => !l);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [correcting, current, preview, setStatus, skip]);

  const batchToast = (b: ReviewBatchRead) =>
    setToast({
      text: `${b.action === "confirmed" ? "Accepted" : "Rejected"} ${b.count} event${b.count === 1 ? "" : "s"} as one batch`,
      undo: async () => {
        const res = await browserApi<ReviewBatchRead>(`/review/batches/${b.id}/undo`, { method: "POST" });
        if (!res.ok) return setError(res.message);
        setToast({ text: `Undid the batch: ${res.data.undone_count} event${res.data.undone_count === 1 ? "" : "s"} back in the queue` });
        await refresh();
      },
    });

  const bulkSelected = async (action: "confirmed" | "rejected") => {
    if (!selected.size) return;
    setBusy(true);
    const res = await browserApi<ReviewBatchRead>("/review/bulk", { method: "POST", body: { filters: { ...bulkFilters({}), event_ids: [...selected] }, action } });
    setBusy(false);
    if (!res.ok) return setError(res.message);
    setReviewed((n) => n + res.data.count);
    batchToast(res.data);
    await refresh();
  };

  const openPreview = async (action: "confirmed" | "rejected") => {
    setError(null);
    const res = await browserApi<BulkPreview>("/review/bulk/preview", { method: "POST", body: { filters: bulkFilters(query), action } });
    if (!res.ok) return setError(res.message);
    setPreview({ action, data: res.data });
  };

  const applyAll = async () => {
    if (!preview) return;
    setBusy(true);
    const res = await browserApi<ReviewBatchRead>("/review/bulk", { method: "POST", body: { filters: bulkFilters(query), action: preview.action } });
    setBusy(false);
    setPreview(null);
    if (!res.ok) return setError(res.message);
    setReviewed((n) => n + res.data.count);
    batchToast(res.data);
    await refresh();
  };

  const video = current ? videos[current.video.id] : undefined;
  const btn = "inline-flex h-[34px] items-center gap-2 rounded-md px-3 text-xs font-semibold disabled:opacity-50";
  const kbd = (k: string) => <kbd className="rounded border border-current/30 px-1 font-mono text-[10px] opacity-70">{k}</kbd>;

  return (
    <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
      <section className="flex min-w-0 flex-col gap-3" aria-label="Current event">
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-ink-2">
          <span><span className="font-semibold text-ink">{scope}</span> · {total} to review · {reviewed} reviewed this visit</span>
          <label className="flex items-center gap-1.5"><input type="checkbox" checked={loop} onChange={(e) => setLoop(e.target.checked)} /> Loop the clip {kbd("L")}</label>
        </div>
        {!current ? (
          <div className="rounded-lg border border-line bg-subtle px-4 py-10 text-center text-sm" role="status" data-testid="queue-empty">
            <div className="font-semibold">Nothing left to review here</div>
            <p className="mt-1 text-xs text-ink-2">Every event in this view has a verdict. <Link href="/annotation/review" className="underline">Back to all classes</Link></p>
          </div>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2" data-testid="current-event" data-event-id={current.id}>
              <h2 className="text-base font-semibold">{current.movement_class.label}</h2>
              <StatusBadge status={current.status} />
              {current.confidence != null ? <ConfidenceBadge value={current.confidence} modelVersion={`${current.model_version.name} ${current.model_version.version}`} /> : null}
              <SourceBadge source="auto" />
              <span className="font-mono text-xs text-ink-3">{span(current)}</span>
              <span className="text-xs text-ink-2">{current.handedness === "left" ? "Left" : "Right"} hand · {current.fingers.length ? current.fingers.join(", ") : "whole hand"} · {current.object_label ?? "no object"}</span>
              <Link href={`/cv/movements/events/${current.id}`} className="ml-auto text-xs text-ink-2 underline">Full evidence</Link>
            </div>
            <div className="text-xs text-ink-3"><Link href={`/data/videos/${current.video.id}`} className="hover:underline">{current.video.name}</Link>{current.session ? ` · ${current.session.name}` : ""}</div>
            {event && video && event.id === current.id ? <Stage key={current.id} item={current} event={event} video={video} loop={loop} /> : <div className="aspect-video w-full animate-pulse rounded-lg bg-hover" />}
            {correcting && event ? (
              <CorrectForm event={current} classes={classes} onSubmit={correct} onCancel={() => setCorrecting(false)} />
            ) : (
              <div className="flex flex-wrap gap-2" role="group" aria-label="Verdict">
                <button type="button" disabled={busy} onClick={() => void setStatus("confirmed")} className={cn(btn, "bg-ink text-canvas")}>Accept {kbd("A")}</button>
                <button type="button" disabled={busy} onClick={() => void setStatus("rejected")} className={cn(btn, "border border-error-line text-error hover:bg-error-bg")}>Reject {kbd("R")}</button>
                <button type="button" disabled={busy} onClick={() => setCorrecting(true)} className={cn(btn, "border border-line-strong hover:bg-hover")}>Correct {kbd("C")}</button>
                <button type="button" disabled={busy || current.status === "needs_review"} onClick={() => void setStatus("needs_review")} className={cn(btn, "border border-line-strong hover:bg-hover")}>Flag {kbd("F")}</button>
                <button type="button" onClick={() => skip(-1)} disabled={index === 0} className={cn(btn, "ml-auto border border-line-strong hover:bg-hover")}>Previous {kbd("P")}</button>
                <button type="button" onClick={() => skip(1)} disabled={index >= items.length - 1} className={cn(btn, "border border-line-strong hover:bg-hover")}>Skip {kbd("N")}</button>
              </div>
            )}
          </>
        )}
        {error ? <p className="text-xs text-error" role="alert">{error}</p> : null}
        {toast ? (
          <div className="flex items-center gap-3 rounded-md border border-line bg-subtle px-3 py-2 text-xs" role="status" data-testid="toast">
            <span>{toast.text}</span>
            {toast.undo ? <button type="button" onClick={() => void toast.undo?.()} className="font-semibold underline">Undo</button> : null}
            {toast.href ? <Link href={toast.href} className="font-semibold underline">Open the new version</Link> : null}
            <button type="button" onClick={() => setToast(null)} className="ml-auto text-ink-3" aria-label="Dismiss">×</button>
          </div>
        ) : null}
        <details className="text-xs text-ink-2">
          <summary className="cursor-pointer">Keyboard</summary>
          <ul className="mt-1 grid grid-cols-2 gap-1 sm:grid-cols-4">{REVIEW_KEYS.map((k) => <li key={k.key}><kbd className="font-mono">{k.key}</kbd> {k.label}</li>)}</ul>
        </details>
      </section>

      <aside className="flex min-w-0 flex-col rounded-lg border border-line bg-canvas" aria-label="Queue">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2">
          <h2 className="text-[13px] font-semibold">Queue <span className="font-normal text-ink-3">· {total}</span></h2>
          {lead ? (
            <div className="flex gap-1.5">
              <button type="button" onClick={() => void openPreview("confirmed")} disabled={!total} className="h-7 rounded-md border border-line-strong px-2 text-xs font-medium hover:bg-hover disabled:opacity-50">Accept all…</button>
              <button type="button" onClick={() => void openPreview("rejected")} disabled={!total} className="h-7 rounded-md border border-line-strong px-2 text-xs font-medium hover:bg-hover disabled:opacity-50">Reject all…</button>
            </div>
          ) : null}
        </div>
        {preview ? (
          <div className="flex flex-col gap-2 border-b border-line bg-subtle px-3 py-3 text-xs" role="dialog" aria-label="Confirm bulk review" data-testid="bulk-preview">
            <p className="font-semibold">{preview.action === "confirmed" ? "Accept" : "Reject"} {preview.data.count} pending event{preview.data.count === 1 ? "" : "s"} in this view?</p>
            <ul className="flex flex-wrap gap-x-3 text-ink-2">{Object.entries(preview.data.by_class).map(([k, n]) => <li key={k}>{k.replace(/_/g, " ")} {n}</li>)}</ul>
            {preview.data.over_limit ? <p className="text-error">One bulk review changes at most {preview.data.limit}. Narrow the view first.</p> : null}
            <p className="text-ink-3">Recorded as a bulk review by you (not an individual check), and undoable.</p>
            <div className="flex gap-2">
              <button type="button" onClick={() => void applyAll()} disabled={busy || preview.data.over_limit || !preview.data.count} className="h-7 rounded-md bg-ink px-3 font-semibold text-canvas disabled:opacity-50">
                {preview.action === "confirmed" ? "Accept" : "Reject"} {preview.data.count}
              </button>
              <button type="button" onClick={() => setPreview(null)} className="h-7 rounded-md border border-line-strong px-3 font-medium hover:bg-hover">Cancel</button>
            </div>
          </div>
        ) : null}
        {lead && selected.size ? (
          <div className="flex items-center gap-2 border-b border-line px-3 py-2 text-xs" data-testid="selection-bar">
            <span className="font-medium">{selected.size} selected</span>
            <button type="button" disabled={busy} onClick={() => void bulkSelected("confirmed")} className="h-7 rounded-md bg-ink px-2.5 font-semibold text-canvas">Accept</button>
            <button type="button" disabled={busy} onClick={() => void bulkSelected("rejected")} className="h-7 rounded-md border border-error-line px-2.5 font-semibold text-error">Reject</button>
            <button type="button" onClick={() => setSelected(new Set())} className="ml-auto text-ink-3 underline">Clear</button>
          </div>
        ) : null}
        <ol className="max-h-[70vh] overflow-auto" data-testid="queue-list">
          {items.map((it, i) => (
            <li key={it.id} className={cn("flex items-center gap-2 border-b border-line px-3 py-2 text-xs last:border-b-0", i === index && "bg-hover")} data-id={it.id}>
              {lead ? (
                <input type="checkbox" aria-label={`Select ${it.movement_class.label} ${span(it)}`} checked={selected.has(it.id)}
                       onChange={(e) => setSelected((s) => { const n = new Set(s); if (e.target.checked) n.add(it.id); else n.delete(it.id); return n; })} />
              ) : null}
              <button type="button" onClick={() => setIndex(i)} className="flex min-w-0 flex-1 items-center gap-2 text-left">
                <span className="w-5 shrink-0 text-right tabular-nums text-ink-3">{i + 1}</span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">{it.movement_class.label}{it.object_label ? ` · ${it.object_label}` : ""}</span>
                  <span className="block truncate font-mono text-[11px] text-ink-3">{span(it)} · {it.video.name}</span>
                </span>
                {it.status === "needs_review" ? <span className="size-1.5 shrink-0 rounded-full bg-warning" title="Flagged" /> : null}
                {it.confidence != null ? <ConfidenceBadge value={it.confidence} /> : null}
                <span className="w-10 shrink-0 text-right font-mono text-[11px] tabular-nums text-ink-3" title="Priority">{it.priority.toFixed(2)}</span>
              </button>
            </li>
          ))}
        </ol>
        {items.length < total ? <p className="border-t border-line px-3 py-2 text-[11px] text-ink-3">Showing the top {items.length}; more load as you review.</p> : null}
      </aside>
    </div>
  );
}
