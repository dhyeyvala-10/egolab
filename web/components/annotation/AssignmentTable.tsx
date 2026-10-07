"use client";

import Link from "next/link";
import { useState, useTransition } from "react";
import { DataTable, EmptyState, StatusBadge, type Column } from "@/components/ui";
import { useUrlQuery, type Query } from "@/components/data/useUrlQuery";
import { removeAssignment, setAssignmentStatus } from "@/lib/actions/annotation";
import type { AssignmentRead, AssignmentStatus, Page } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";

const NEXT: Record<AssignmentStatus, { to: AssignmentStatus; label: string } | null> = {
  todo: { to: "in_progress", label: "Start" },
  in_progress: { to: "done", label: "Mark done" },
  done: { to: "in_progress", label: "Reopen" },
};

export function AssignmentTable({ page, query, userId, isLead }: { page: Page<AssignmentRead>; query: Query; userId: string; isLead: boolean }) {
  const { set, pending } = useUrlQuery(query);
  const [busy, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const run = (fn: () => Promise<{ error?: string }>) =>
    start(async () => {
      const res = await fn();
      setError(res.error ?? null);
    });

  const columns: Column<AssignmentRead>[] = [
    {
      key: "target",
      header: "Work",
      cell: (a) =>
        a.video ? (
          <div className="min-w-0">
            <Link href={`/annotation/inspector/${a.video.id}`} className="font-medium hover:underline">{a.video.name}</Link>
            <div className="text-xs text-ink-3">Video</div>
          </div>
        ) : a.session ? (
          <div className="min-w-0">
            <Link href={`/annotation/inspector?session_id=${a.session.id}`} className="font-mono text-xs font-medium hover:underline">{a.session.name}</Link>
            <div className="text-xs text-ink-3">Session</div>
          </div>
        ) : null,
    },
    { key: "assignee", header: "Assignee", cell: (a) => a.assignee.name },
    { key: "status", header: "Status", cell: (a) => <StatusBadge status={a.status} /> },
    {
      key: "progress",
      header: "Annotated",
      align: "right",
      cell: (a) => (
        <span title="Videos with at least one human annotation">
          {a.progress.annotated} / {a.progress.videos}
        </span>
      ),
    },
    { key: "note", header: "Instructions", cell: (a) => (a.note ? <span className="line-clamp-2 text-xs text-ink-2">{a.note}</span> : null) },
    { key: "assigned_by", header: "Assigned by", cell: (a) => a.assigned_by?.name },
    { key: "created_at", header: "Assigned", className: "whitespace-nowrap", cell: (a) => formatDateTime(a.created_at) },
    {
      key: "actions",
      header: "",
      cell: (a) => {
        const next = NEXT[a.status];
        const mine = a.assignee.id === userId;
        return (
          <div className="flex justify-end gap-1.5">
            {next && (mine || isLead) ? (
              <button type="button" disabled={busy} onClick={() => run(() => setAssignmentStatus(a.id, next.to))} className="h-7 rounded-md border border-line px-2 text-xs font-medium hover:bg-hover disabled:opacity-50">
                {next.label}
              </button>
            ) : null}
            {isLead ? (
              <button type="button" disabled={busy} onClick={() => run(() => removeAssignment(a.id))} className="h-7 rounded-md px-2 text-xs text-ink-2 hover:bg-hover disabled:opacity-50">
                Remove
              </button>
            ) : null}
          </div>
        );
      },
    },
  ];

  const select = "h-[30px] rounded-md border border-line-strong bg-canvas px-2 text-[13px]";
  return (
    <div className="flex flex-col gap-2">
      {error ? <p role="alert" className="text-xs text-error">{error}</p> : null}
      <DataTable
        className={pending ? "opacity-70" : undefined}
        columns={columns}
        rows={page.items}
        rowKey={(a) => a.id}
        toolbar={
          <>
            <select aria-label="Whose work" className={select} value={query.mine ?? ""} onChange={(e) => set({ mine: e.target.value || undefined })}>
              <option value="">Everyone</option>
              <option value="true">Assigned to me</option>
            </select>
            <select aria-label="Status" className={select} value={query.status ?? ""} onChange={(e) => set({ status: e.target.value || undefined })}>
              <option value="">Any status</option>
              <option value="todo">To do</option>
              <option value="in_progress">In progress</option>
              <option value="done">Done</option>
            </select>
          </>
        }
        page={{ index: Math.floor(page.offset / page.limit), size: page.limit, total: page.total }}
        onPageChange={(i) => set({ offset: String(i * page.limit) }, { resetPage: false })}
        caption="Assignments"
        empty={
          <EmptyState
            size="compact"
            title={query.mine || query.status ? "Nothing matches these filters" : "Nothing assigned yet"}
            description={isLead ? "Assign a session or video above." : "A reviewer or admin assigns sessions and videos to annotators."}
          />
        }
      />
    </div>
  );
}
