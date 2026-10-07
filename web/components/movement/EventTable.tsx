"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ConfidenceBadge, SourceBadge, DataTable, EmptyState, StatusBadge, type Column } from "@/components/ui";
import { useUrlQuery, type Query } from "@/components/data/useUrlQuery";
import type { MovementClassRead, MovementEventSummary, Page, Ref } from "@/lib/api/types";

const FINGERS = ["thumb", "index", "middle", "ring", "pinky"];
const STATUSES = ["auto_detected", "needs_review", "confirmed", "rejected", "corrected"];
const select = "h-[30px] rounded-md border border-line-strong bg-canvas px-2 text-[13px]";

export function formatSpan(e: { start_frame: number; end_frame: number; start_s: number; end_s: number }): string {
  return `f${e.start_frame}–f${e.end_frame} · ${e.start_s.toFixed(2)}–${e.end_s.toFixed(2)} s`;
}

const columns: Column<MovementEventSummary>[] = [
  {
    key: "event",
    header: "Event",
    cell: (e) => (
      <div className="min-w-0">
        <Link href={`/cv/movements/events/${e.id}`} className="font-medium hover:underline" onClick={(ev) => ev.stopPropagation()}>
          {e.label}
        </Link>
        <div className="truncate font-mono text-[11px] text-ink-3">{formatSpan(e)}</div>
      </div>
    ),
  },
  {
    key: "video",
    header: "Video",
    cell: (e) => (
      <Link href={`/annotation/inspector/${e.video.id}?frame=${e.start_frame}`} className="truncate hover:underline" onClick={(ev) => ev.stopPropagation()} title="Open in the inspector at this event">
        {e.video.name}
      </Link>
    ),
  },
  { key: "hand", header: "Hand", cell: (e) => `${e.handedness === "left" ? "Left" : "Right"} #${e.hand_track_id}` },
  { key: "fingers", header: "Fingers", cell: (e) => (e.fingers.length ? e.fingers.join(", ") : <span className="text-ink-3">whole hand</span>) },
  { key: "object", header: "Object", cell: (e) => (e.object_label ? `${e.object_label} #${e.object_track_id}` : <span className="text-ink-3">—</span>) },
  { key: "confidence", header: "Confidence", cell: (e) => (e.confidence != null ? <ConfidenceBadge value={e.confidence} modelVersion={`${e.model_version.name} ${e.model_version.version}`} /> : <SourceBadge source="auto_corrected" />) },
  { key: "status", header: "Status", cell: (e) => <StatusBadge status={e.status} /> },
];

/** Movement events from each video's latest classification run, filtered and paged by the API. */
export function EventTable({ page, query, classes, videos }: { page: Page<MovementEventSummary>; query: Query; classes: MovementClassRead[]; videos: Ref[] }) {
  const router = useRouter();
  const { set, pending } = useUrlQuery(query);
  const filtered = Object.keys(query).some((k) => k !== "offset" && k !== "sort" && query[k]);
  return (
    <DataTable
      className={pending ? "opacity-70" : undefined}
      columns={columns}
      rows={page.items}
      rowKey={(e) => e.id}
      onRowClick={(e) => router.push(`/cv/movements/events/${e.id}`)}
      toolbar={
        <div className="flex flex-wrap items-center gap-2">
          {videos.length ? (
            <select aria-label="Video" className={`${select} max-w-56`} value={query.video_id ?? ""} onChange={(e) => set({ video_id: e.target.value || undefined })}>
              <option value="">All videos</option>
              {videos.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
            </select>
          ) : null}
          <select aria-label="Class" className={select} value={query.class ?? ""} onChange={(e) => set({ class: e.target.value || undefined })}>
            <option value="">Any class</option>
            {classes.map((c) => <option key={c.id} value={c.name}>{c.label}</option>)}
          </select>
          <select aria-label="Status" className={select} value={query.status ?? ""} onChange={(e) => set({ status: e.target.value || undefined })}>
            <option value="">Any status</option>
            {STATUSES.map((s) => <option key={s} value={s}>{s.replace("_", " ")}</option>)}
          </select>
          <select aria-label="Hand" className={select} value={query.handedness ?? ""} onChange={(e) => set({ handedness: e.target.value || undefined })}>
            <option value="">Either hand</option>
            <option value="left">Left</option>
            <option value="right">Right</option>
          </select>
          <select aria-label="Finger" className={select} value={query.finger ?? ""} onChange={(e) => set({ finger: e.target.value || undefined })}>
            <option value="">Any finger</option>
            {FINGERS.map((f) => <option key={f} value={f}>{f}</option>)}
          </select>
          <select aria-label="Confidence" className={select} value={query.max_confidence ?? ""} onChange={(e) => set({ max_confidence: e.target.value || undefined })}>
            <option value="">Any confidence</option>
            <option value="0.6">Below 0.6</option>
            <option value="0.8">Below 0.8</option>
          </select>
          <select aria-label="Sort" className={select} value={query.sort ?? "start"} onChange={(e) => set({ sort: e.target.value === "start" ? undefined : e.target.value })}>
            <option value="start">In video order</option>
            <option value="confidence">Least confident first</option>
            <option value="-created">Newest first</option>
          </select>
        </div>
      }
      page={{ index: Math.floor(page.offset / page.limit), size: page.limit, total: page.total }}
      onPageChange={(i) => set({ offset: String(i * page.limit) }, { resetPage: false })}
      caption="Movement events"
      empty={
        <EmptyState
          size="compact"
          title={filtered ? "No events match these filters" : "No movement events yet"}
          description={filtered ? "Try another class, status, or video." : "Run hand tracking on a video: object detection and movement classification follow on their own, and the events appear here and on the inspector's timeline."}
        />
      }
    />
  );
}
