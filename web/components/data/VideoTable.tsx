"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { DataTable, EmptyState, StatusBadge, type Column, type SortState } from "@/components/ui";
import type { Page, Ref, VideoSummary } from "@/lib/api/types";
import { formatBytes, formatCount, formatDateTime, formatDuration, formatFps, formatResolution } from "@/lib/format";
import { useUrlQuery, type Query } from "./useUrlQuery";

const SOURCE_LABEL: Record<string, string> = { file: "File", archive_member: "From ZIP", image_sequence: "Image sequence" };

/** First frame of the thumbnail strip (10 tiles, left to right). */
function Thumb({ url }: { url: string | null | undefined }) {
  if (!url) return <div className="h-9 w-16 rounded-sm border border-line bg-hover" aria-hidden />;
  return (
    <div
      aria-hidden
      className="h-9 w-16 rounded-sm border border-line bg-hover bg-no-repeat"
      style={{ backgroundImage: `url(${url})`, backgroundSize: "640px 36px", backgroundPosition: "0 0" }}
    />
  );
}

function columns(showSession: boolean, hrefFor: (v: VideoSummary) => string): Column<VideoSummary>[] {
  const cols: Column<VideoSummary>[] = [
    { key: "thumb", header: "", cell: (v) => <Thumb url={v.thumbnails_url} />, className: "w-[76px] py-1.5" },
    {
      key: "original_filename",
      header: "Video",
      sortable: true,
      cell: (v) => (
        <div className="min-w-0">
          <Link href={hrefFor(v)} className="font-medium hover:underline" onClick={(e) => e.stopPropagation()}>
            {v.original_filename}
          </Link>
          <div className="text-xs text-ink-3">{SOURCE_LABEL[v.source_kind] ?? v.source_kind}</div>
        </div>
      ),
    },
  ];
  if (showSession) {
    cols.push({
      key: "session",
      header: "Session",
      cell: (v) =>
        v.session ? (
          <Link href={`/data/sessions/${v.session.id}`} className="font-mono text-xs hover:underline" onClick={(e) => e.stopPropagation()}>
            {v.session.name}
          </Link>
        ) : (
          <span className="text-xs text-ink-3">Unassigned</span>
        ),
    });
  }
  cols.push(
    { key: "status", header: "Status", cell: (v) => <StatusBadge status={v.status} /> },
    { key: "duration_s", header: "Duration", sortable: true, align: "right", cell: (v) => formatDuration(v.duration_s) },
    { key: "width", header: "Resolution", sortable: true, align: "right", cell: (v) => formatResolution(v.width, v.height) },
    { key: "fps", header: "FPS", sortable: true, align: "right", cell: (v) => formatFps(v.fps) },
    { key: "frame_count", header: "Frames", sortable: true, align: "right", cell: (v) => formatCount(v.frame_count) },
    { key: "codec", header: "Codec", cell: (v) => (v.codec ? <span className="font-mono text-xs">{v.codec}</span> : null) },
    { key: "size_bytes", header: "Size", sortable: true, align: "right", cell: (v) => formatBytes(v.size_bytes) },
    { key: "created_at", header: "Added", sortable: true, className: "whitespace-nowrap", cell: (v) => formatDateTime(v.created_at) },
  );
  return cols;
}

export function VideoTable({
  page,
  query,
  sessions,
  showSession = true,
  emptyAction,
  linkBase = "/data/videos",
  showStatusFilter = true,
}: {
  page: Page<VideoSummary>;
  query: Query;
  sessions?: Ref[];
  showSession?: boolean;
  emptyAction?: React.ReactNode;
  /** Rows link to `${linkBase}/${id}` (default: the video's page). */
  linkBase?: string;
  showStatusFilter?: boolean;
}) {
  const router = useRouter();
  const hrefFor = (v: VideoSummary) => `${linkBase}/${v.id}`;
  const { set, pending } = useUrlQuery(query);
  const [q, setQ] = useState(query.q ?? "");

  useEffect(() => {
    if ((query.q ?? "") === q) return;
    const t = setTimeout(() => set({ q: q || undefined }), 300);
    return () => clearTimeout(t);
  }, [q, query.q, set]);

  const sort: SortState | null = query.sort ? { key: query.sort, dir: query.order === "asc" ? "asc" : "desc" } : { key: "created_at", dir: "desc" };
  const filtered = Boolean(query.q || query.status || query.session_id || query.source_kind || query.unassigned);

  const select = "h-[30px] rounded-md border border-line-strong bg-canvas px-2 text-[13px]";
  const toolbar = (
    <>
      {showStatusFilter ? (
        <select aria-label="Status" className={select} value={query.status ?? ""} onChange={(e) => set({ status: e.target.value || undefined })}>
          <option value="">Any status</option>
          <option value="ready">Ready</option>
          <option value="processing">Processing</option>
          <option value="corrupt">Corrupt</option>
        </select>
      ) : null}
      <select aria-label="Source" className={select} value={query.source_kind ?? ""} onChange={(e) => set({ source_kind: e.target.value || undefined })}>
        <option value="">Any source</option>
        <option value="file">File</option>
        <option value="archive_member">From ZIP</option>
        <option value="image_sequence">Image sequence</option>
      </select>
      {sessions ? (
        <select
          aria-label="Session"
          className={`${select} max-w-[220px]`}
          value={query.unassigned ? "__none" : (query.session_id ?? "")}
          onChange={(e) =>
            e.target.value === "__none"
              ? set({ session_id: undefined, unassigned: "true" })
              : set({ session_id: e.target.value || undefined, unassigned: undefined })
          }
        >
          <option value="">Any session</option>
          <option value="__none">Unassigned</option>
          {sessions.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      ) : null}
    </>
  );

  return (
    <DataTable
      className={pending ? "opacity-70" : undefined}
      columns={columns(showSession, hrefFor)}
      rows={page.items}
      rowKey={(v) => v.id}
      onRowClick={(v) => router.push(hrefFor(v))}
      sort={sort}
      onSortChange={(s) => set({ sort: s.key, order: s.dir })}
      filter={q}
      onFilterChange={setQ}
      filterPlaceholder="Search file names"
      toolbar={toolbar}
      page={{ index: Math.floor(page.offset / page.limit), size: page.limit, total: page.total }}
      onPageChange={(i) => set({ offset: String(i * page.limit) }, { resetPage: false })}
      caption="Videos"
      empty={
        <EmptyState
          size="compact"
          title={filtered ? "No videos match these filters" : "No videos yet"}
          description={filtered ? "Clear a filter to see more." : "Uploaded videos appear here once they're ingested."}
          action={filtered ? undefined : emptyAction}
        />
      }
    />
  );
}
