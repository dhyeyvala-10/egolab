"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { DataTable, EmptyState, StatusBadge, type Column } from "@/components/ui";
import type { Page, SessionSummary } from "@/lib/api/types";
import { formatBytes, formatDateTime, formatDuration } from "@/lib/format";
import { useUrlQuery, type Query } from "./useUrlQuery";

const COLUMNS: Column<SessionSummary>[] = [
  {
    key: "name",
    header: "Session",
    sortable: true,
    cell: (s) => (
      <Link href={`/data/sessions/${s.id}`} className="font-mono text-xs font-semibold hover:underline" onClick={(e) => e.stopPropagation()}>
        {s.name}
      </Link>
    ),
  },
  { key: "task", header: "Task", cell: (s) => s.task },
  { key: "environment", header: "Environment", cell: (s) => s.environment },
  { key: "operator", header: "Operator", cell: (s) => s.operator?.name },
  { key: "device", header: "Device", cell: (s) => s.device?.name },
  { key: "video_count", header: "Videos", sortable: true, align: "right", cell: (s) => s.stats.video_count },
  {
    key: "state",
    header: "State",
    cell: (s) =>
      s.stats.corrupt_count > 0 ? (
        <StatusBadge status="corrupt" label={`${s.stats.corrupt_count} corrupt`} />
      ) : s.stats.processing_count > 0 ? (
        <StatusBadge status="processing" label={`${s.stats.processing_count} processing`} />
      ) : s.stats.video_count > 0 ? (
        <StatusBadge status="ready" />
      ) : (
        <span className="text-xs text-ink-3">No videos</span>
      ),
  },
  { key: "total_duration_s", header: "Footage", sortable: true, align: "right", cell: (s) => formatDuration(s.stats.total_duration_s) },
  { key: "size", header: "Size", align: "right", cell: (s) => formatBytes(s.stats.total_size_bytes) },
  { key: "started_at", header: "Started", sortable: true, className: "whitespace-nowrap", cell: (s) => (s.started_at ? formatDateTime(s.started_at) : null) },
];

export function SessionTable({ page, query }: { page: Page<SessionSummary>; query: Query }) {
  const router = useRouter();
  const { set, pending } = useUrlQuery(query);
  const [q, setQ] = useState(query.q ?? "");
  useEffect(() => {
    if ((query.q ?? "") === q) return;
    const t = setTimeout(() => set({ q: q || undefined }), 300);
    return () => clearTimeout(t);
  }, [q, query.q, set]);

  return (
    <DataTable
      className={pending ? "opacity-70" : undefined}
      columns={COLUMNS}
      rows={page.items}
      rowKey={(s) => s.id}
      onRowClick={(s) => router.push(`/data/sessions/${s.id}`)}
      sort={{ key: query.sort ?? "created_at", dir: query.order === "asc" ? "asc" : "desc" }}
      onSortChange={(s) => set({ sort: s.key, order: s.dir })}
      filter={q}
      onFilterChange={setQ}
      filterPlaceholder="Search name, task, environment, location"
      page={{ index: Math.floor(page.offset / page.limit), size: page.limit, total: page.total }}
      onPageChange={(i) => set({ offset: String(i * page.limit) }, { resetPage: false })}
      caption="Sessions"
      empty={
        <EmptyState
          size="compact"
          title={query.q ? "No sessions match this search" : "No sessions yet"}
          description={query.q ? undefined : "Create a session, then upload its videos."}
          action={
            query.q ? undefined : (
              <Link href="/data/sessions/new" className="inline-flex h-[30px] items-center rounded-md border border-line-strong px-3 font-medium hover:bg-hover">
                New session
              </Link>
            )
          }
        />
      }
    />
  );
}
