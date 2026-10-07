"use client";

import { X } from "lucide-react";
import Link from "next/link";
import { useState, useTransition } from "react";
import { DataTable, EmptyState, StatusBadge, type Column } from "@/components/ui";
import type { Ref, UploadRead } from "@/lib/api/types";
import { cancelUpload } from "@/lib/actions/admin";
import { cn } from "@/lib/cn";
import { formatBytes, formatDateTime } from "@/lib/format";
import { useNow } from "@/lib/useNow";

function summary(u: UploadRead): React.ReactNode {
  if (u.status === "failed" || u.status === "rejected") return <span className="text-error">{u.error}</span>;
  if (u.status === "awaiting_approval") return <span className="text-warning">{u.approval_reason}</span>;
  const r = u.result as { created?: string[]; duplicates?: unknown[]; corrupt?: string[]; sidecars?: string[] };
  const parts = [
    r.created?.length ? `${r.created.length} added` : null,
    r.duplicates?.length ? `${r.duplicates.length} duplicate` : null,
    r.corrupt?.length ? `${r.corrupt.length} corrupt` : null,
    r.sidecars?.length ? `${r.sidecars.length} sidecar` : null,
  ].filter(Boolean);
  return parts.join(", ");
}

/** Seconds since the last piece arrived: a paused or abandoned upload stops moving. */
export function sinceText(iso: string | null | undefined, now: number): string {
  if (!iso) return "nothing received yet";
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (s < 60) return `last data ${s} s ago`;
  if (s < 3600) return `last data ${Math.round(s / 60)} min ago`;
  return `last data ${Math.round(s / 3600)} h ago`;
}

/** No data for this long while "uploading" means the uploader stopped (closed the page, lost the network). */
export const STALLED_MS = 2 * 60 * 1000;

export function Progress({ upload, now }: { upload: UploadRead; now: number }) {
  const got = upload.received_bytes ?? 0;
  const pct = upload.size_bytes ? Math.min(100, Math.round((got / upload.size_bytes) * 100)) : 0;
  const last = upload.last_data_at ?? upload.created_at;
  const stalled = now - new Date(last).getTime() > STALLED_MS;
  return (
    <div className="flex min-w-[180px] flex-col gap-1">
      <div className="h-1 overflow-hidden rounded bg-hover" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label={`${upload.filename} received`}>
        <div className={cn("h-full rounded", stalled ? "bg-ink-3" : "bg-running")} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs tabular-nums text-ink-2">
        {formatBytes(got)} of {formatBytes(upload.size_bytes)} ({pct}%) · {stalled ? <strong className="text-warning">paused, {sinceText(upload.last_data_at, now)}</strong> : sinceText(upload.last_data_at, now)}
      </span>
    </div>
  );
}

function CancelButton({ upload }: { upload: UploadRead }) {
  const [pending, start] = useTransition();
  const [error, setError] = useState<string>();
  return (
    <div className="flex flex-col items-end gap-1">
      <button
        type="button"
        aria-label={`Cancel ${upload.filename}`}
        disabled={pending}
        onClick={() => {
          if (window.confirm(`Cancel the upload of ${upload.filename}? What was sent is thrown away.`))
            start(async () => setError((await cancelUpload(upload.id)).error));
        }}
        className="inline-flex h-7 items-center gap-1 rounded-md border border-line px-2 text-xs font-semibold hover:bg-hover disabled:opacity-50"
      >
        <X className="size-3" aria-hidden /> Cancel
      </button>
      {error ? <span className="text-xs text-error">{error}</span> : null}
    </div>
  );
}

const OPEN = new Set(["uploading", "awaiting_approval"]);

export function RecentUploads({ uploads, sessions, showWho = false, canCancel = () => false }: {
  uploads: UploadRead[];
  sessions: Ref[];
  /** The admin sees everyone's uploads, so the list says whose each one is. */
  showWho?: boolean;
  canCancel?: (u: UploadRead) => boolean;
}) {
  const names = new Map(sessions.map((s) => [s.id, s.name]));
  const now = useNow(1000);
  const columns: Column<UploadRead>[] = [
    {
      key: "filename",
      header: "File",
      cell: (u) =>
        u.video_id ? (
          <Link href={`/data/videos/${u.video_id}`} className="font-medium hover:underline">{u.filename}</Link>
        ) : (
          <span className="font-medium">{u.filename}</span>
        ),
    },
    ...(showWho
      ? [{ key: "uploaded_by_email", header: "Who", cell: (u: UploadRead) => u.uploaded_by_name || u.uploaded_by_email || "—" } satisfies Column<UploadRead>]
      : []),
    { key: "kind", header: "Kind", cell: (u) => <span className="capitalize">{u.kind}</span> },
    {
      key: "status",
      header: "Status",
      cell: (u) => <StatusBadge status={u.status} label={u.status === "awaiting_approval" ? "Waiting for admin" : undefined} />,
    },
    { key: "session_id", header: "Session", cell: (u) => (u.session_id ? <span className="font-mono text-xs">{names.get(u.session_id) ?? u.session_id.slice(0, 8)}</span> : null) },
    { key: "result", header: "Progress / result", cell: (u) => (u.status === "uploading" ? <Progress upload={u} now={now} /> : summary(u)) },
    { key: "size_bytes", header: "Size", align: "right", cell: (u) => formatBytes(u.size_bytes) },
    { key: "created_at", header: "Started", className: "whitespace-nowrap", cell: (u) => formatDateTime(u.created_at) },
    { key: "id", header: "", align: "right", cell: (u) => (OPEN.has(u.status) && canCancel(u) ? <CancelButton upload={u} /> : null) },
  ];
  return (
    <DataTable
      columns={columns}
      rows={uploads}
      rowKey={(u) => u.id}
      caption="Recent uploads"
      empty={<EmptyState size="compact" title="No uploads yet" />}
    />
  );
}
