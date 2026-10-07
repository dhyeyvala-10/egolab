"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { ConfidenceBadge, DataTable, EmptyState, StatusBadge, type Column } from "@/components/ui";
import { useUrlQuery, type Query } from "@/components/data/useUrlQuery";
import type { CvRunKind, CvRunSummary, Page } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";

const fmt = new Intl.NumberFormat("en-US");

const done = (r: CvRunSummary) => r.status === "succeeded";

function columns(base: string, kind: CvRunKind): Column<CvRunSummary>[] {
  const video: Column<CvRunSummary> = {
    key: "video",
    header: "Video",
    cell: (r) => (
      <div className="min-w-0">
        <Link href={`${base}/${r.id}`} className="font-medium hover:underline" onClick={(e) => e.stopPropagation()}>
          {r.video.name}
        </Link>
        <div className="truncate text-xs text-ink-3" title={r.model_version ? `${r.model_version.name} ${r.model_version.version}` : r.adapter}>
          {r.model_version ? r.model_version.name : r.adapter}
          {r.stride > 1 ? ` · every ${r.stride} frames` : ""}
        </div>
      </div>
    ),
  };
  const status: Column<CvRunSummary> = {
    key: "status",
    header: "Status",
    cell: (r) => (
      <span title={r.status === "waiting" ? "Waiting for the runs it reads to finish" : (r.error ?? undefined)}>
        <StatusBadge status={r.status} />
      </span>
    ),
  };
  const frames: Column<CvRunSummary> = {
    key: "frames",
    header: "Frames",
    align: "right",
    cell: (r) => (r.frames_total ? `${fmt.format(r.frames_processed)} / ${fmt.format(Math.ceil(r.frames_total / r.stride))}` : fmt.format(r.frames_processed)),
  };
  const confidence = (header: string): Column<CvRunSummary> => ({
    key: "confidence",
    header,
    cell: (r) => (r.mean_confidence != null ? <ConfidenceBadge value={r.mean_confidence} modelVersion={r.model_version?.version} /> : null),
  });
  const started: Column<CvRunSummary> = { key: "created_at", header: "Started", className: "whitespace-nowrap", cell: (r) => formatDateTime(r.started_at ?? r.created_at) };
  if (kind === "object_detection") {
    return [
      video, status, frames,
      { key: "tracks", header: "Objects", align: "right", cell: (r) => (done(r) ? r.tracks : null) },
      { key: "detections", header: "Detections", align: "right", cell: (r) => (done(r) ? fmt.format(r.detections) : null) },
      { key: "missing", header: "Missing detections", align: "right", cell: (r) => (done(r) ? fmt.format(r.missing_detections) : null) },
      confidence("Mean score"), started,
    ];
  }
  if (kind === "movement") {
    return [
      video, status, frames,
      { key: "detections", header: "Events", align: "right", cell: (r) => (done(r) ? fmt.format(r.detections) : null) },
      { key: "inputs", header: "Reads", cell: (r) => <span className="text-xs text-ink-2">{Object.keys(r.inputs).map((k) => k.replace("_", " ")).join(" + ") || "—"}</span> },
      confidence("Mean confidence"), started,
    ];
  }
  return [
    video, status, frames,
    { key: "hands", header: "With a hand", align: "right", cell: (r) => (done(r) && r.frames_processed ? `${((r.frames_with_hands / r.frames_processed) * 100).toFixed(1)}%` : null) },
    { key: "tracks", header: "Tracks", align: "right", cell: (r) => (done(r) ? r.tracks : null) },
    { key: "missing", header: "Missing detections", align: "right", cell: (r) => (done(r) ? fmt.format(r.missing_detections) : null) },
    { key: "failures", header: "Tracking failures", align: "right", cell: (r) => (done(r) ? r.tracking_failures : null) },
    confidence("Mean confidence"), started,
  ];
}

const NOUN: Record<CvRunKind, { caption: string; empty: string; hint: string }> = {
  hand_tracking: { caption: "Tracking runs", empty: "No tracking runs yet", hint: "Run hand tracking on a video to see detections, tracks, and finger kinematics." },
  object_detection: { caption: "Object detection runs", empty: "No object detection runs yet", hint: "Run object detection on a video to see the objects the hands work with." },
  movement: { caption: "Movement classification runs", empty: "No classification runs yet", hint: "Movement classification runs on a video's hand (and object) runs, by default right after them." },
};

/** Runs, newest first. Refreshes itself while any run on the page is queued or running. */
export function RunTable({
  page,
  query,
  base,
  kind = "hand_tracking",
  emptyAction,
  controls = true,
}: {
  page: Page<CvRunSummary>;
  query: Query;
  base: string;
  kind?: CvRunKind;
  emptyAction?: React.ReactNode;
  /** Status filter and paging (off where another table on the page owns the URL query). */
  controls?: boolean;
}) {
  const router = useRouter();
  const { set, pending } = useUrlQuery(query);
  const active = page.items.some((r) => r.status === "queued" || r.status === "running" || r.status === "waiting");
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => router.refresh(), 3000);
    return () => clearInterval(t);
  }, [active, router]);

  const select = "h-[30px] rounded-md border border-line-strong bg-canvas px-2 text-[13px]";
  return (
    <DataTable
      className={pending ? "opacity-70" : undefined}
      columns={columns(base, kind)}
      rows={page.items}
      rowKey={(r) => r.id}
      onRowClick={(r) => router.push(`${base}/${r.id}`)}
      toolbar={
        !controls ? undefined : <select aria-label="Status" className={select} value={query.status ?? ""} onChange={(e) => set({ status: e.target.value || undefined })}>
          <option value="">Any status</option>
          <option value="succeeded">Succeeded</option>
          <option value="running">Running</option>
          <option value="queued">Queued</option>
          <option value="waiting">Waiting</option>
          <option value="failed">Failed</option>
        </select>
      }
      page={controls ? { index: Math.floor(page.offset / page.limit), size: page.limit, total: page.total } : undefined}
      onPageChange={controls ? (i) => set({ offset: String(i * page.limit) }, { resetPage: false }) : undefined}
      caption={NOUN[kind].caption}
      empty={<EmptyState size="compact" title={query.status ? "No runs with this status" : NOUN[kind].empty} description={NOUN[kind].hint} action={emptyAction} />}
    />
  );
}
