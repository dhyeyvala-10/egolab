"use client";

import { Flag, RotateCcw } from "lucide-react";
import { useEffect, useState } from "react";
import { SourceBadge } from "@/components/ui";
import { browserApi } from "@/lib/api/browser";
import type { AnnotationRead, Page } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import type { View } from "@/lib/inspector/view";
import { TYPE_LABEL } from "./AnnotationForm";

const LIMIT = 100;

/** Annotations overlapping the timeline's visible window (or the deleted ones, to restore). */
export function AnnotationList({
  videoId,
  view,
  version,
  selectedId,
  canEdit,
  onSelect,
  onRestore,
}: {
  videoId: string;
  view: View;
  version: number;
  selectedId: string | null;
  canEdit: boolean;
  onSelect: (a: AnnotationRead) => void;
  onRestore: (a: AnnotationRead) => void;
}) {
  const [deleted, setDeleted] = useState(false);
  const [page, setPage] = useState<Page<AnnotationRead> | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    const timer = setTimeout(() => {
      const query = deleted ? { deleted_only: true, limit: LIMIT } : { frame_from: view.start, frame_to: view.end, limit: LIMIT };
      browserApi<Page<AnnotationRead>>(`/videos/${videoId}/annotations`, { query, signal: ctrl.signal })
        .then((res) => {
          if (res.ok) {
            setPage(res.data);
            setError(null);
          } else setError(res.message);
        })
        .catch(() => undefined);
    }, 150);
    return () => {
      clearTimeout(timer);
      ctrl.abort();
    };
  }, [videoId, view.start, view.end, version, deleted]);

  return (
    <div className="flex min-h-0 flex-col gap-2">
      <div className="flex items-center justify-between gap-2 text-xs">
        <span className="text-ink-2">
          {page ? `${page.total.toLocaleString("en-US")} ${deleted ? "deleted" : "in view"}` : "Loading…"}
          {page && page.total > page.items.length ? ` · first ${page.items.length}` : ""}
        </span>
        <label className="flex items-center gap-1.5 text-ink-2">
          <input type="checkbox" checked={deleted} onChange={(e) => setDeleted(e.target.checked)} />
          Show deleted
        </label>
      </div>
      {error ? <p className="text-xs text-error">{error}</p> : null}
      {page && page.items.length === 0 ? (
        <p className="rounded-md border border-dashed border-line px-3 py-6 text-center text-xs text-ink-3">
          {deleted ? "Nothing has been deleted from this video." : canEdit ? "No annotations in view. Press A to create one." : "No annotations in view."}
        </p>
      ) : null}
      <ul className="flex min-h-0 flex-col divide-y divide-line overflow-y-auto rounded-md border border-line" data-testid="annotation-list">
        {page?.items.map((a) => (
          <li key={a.id} className={cn("flex items-center gap-2 px-2.5 py-2", selectedId === a.id && "bg-hover")}>
            <button type="button" onClick={() => onSelect(a)} className="flex min-w-0 flex-1 flex-col items-start text-left">
              <span className="flex max-w-full items-center gap-1.5">
                {a.needs_review ? <Flag className="size-3 flex-none text-warning" aria-label="Needs review" /> : null}
                <span className={cn("truncate text-[13px] font-medium", deleted && "line-through")}>{a.label}</span>
              </span>
              <span className="font-mono text-[11px] text-ink-3">
                {TYPE_LABEL[a.type]} · f{a.frame_start}
                {a.frame_end !== a.frame_start ? `–f${a.frame_end}` : ""}
              </span>
            </button>
            <SourceBadge source={a.source} />
            {deleted && canEdit ? (
              <button
                type="button"
                onClick={() => onRestore(a)}
                aria-label={`Restore ${a.label}`}
                className="grid size-7 place-items-center rounded-md border border-line hover:bg-canvas"
              >
                <RotateCcw className="size-3.5" aria-hidden />
              </button>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}
