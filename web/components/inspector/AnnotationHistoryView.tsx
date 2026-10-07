"use client";

import { useEffect, useState } from "react";
import { SourceBadge } from "@/components/ui";
import { browserApi } from "@/lib/api/browser";
import type { AnnotationHistory, RevisionRead } from "@/lib/api/types";

const ACTION: Record<RevisionRead["action"], string> = {
  created: "Created",
  updated: "Edited",
  flagged: "Marked for review",
  unflagged: "Review mark removed",
  deleted: "Deleted",
  restored: "Restored",
  superseded: "Replaced by a human correction",
};

function show(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") {
    const box = (value as { box?: number[] }).box;
    if (box) return `box [${box.map((n) => n.toFixed(3)).join(", ")}]`;
    const points = (value as { points?: unknown[] }).points;
    if (points) return `${points.length} point${points.length === 1 ? "" : "s"}`;
    return JSON.stringify(value);
  }
  return String(value);
}

/** Every revision of the selected annotation, newest first, with what changed and who changed it. */
export function AnnotationHistoryView({ annotationId, version, onOpen }: { annotationId: string; version: number; onOpen: (id: string) => void }) {
  const [history, setHistory] = useState<AnnotationHistory | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    browserApi<AnnotationHistory>(`/annotations/${annotationId}/history`, { signal: ctrl.signal })
      .then((res) => (res.ok ? setHistory(res.data) : setError(res.message)))
      .catch(() => undefined);
    return () => ctrl.abort();
  }, [annotationId, version]);

  if (error) return <p className="text-xs text-error">{error}</p>;
  if (!history || history.annotation.id !== annotationId) return <p className="text-xs text-ink-3">Loading history…</p>;

  return (
    <div className="flex flex-col gap-3" data-testid="annotation-history">
      {history.parent ? (
        <div className="rounded-md border border-ai-line bg-ai-bg px-2.5 py-2 text-xs">
          Corrects the AI prediction{" "}
          <button type="button" className="font-semibold underline" onClick={() => onOpen(history.parent!.id)}>
            “{history.parent.label}”
          </button>
          {history.parent.confidence != null ? ` (confidence ${history.parent.confidence.toFixed(2)})` : ""}, which is kept unchanged.
        </div>
      ) : null}
      {history.corrections.length ? (
        <div className="rounded-md border border-human-line bg-human-bg px-2.5 py-2 text-xs">
          Corrected by{" "}
          {history.corrections.map((c, i) => (
            <span key={c.id}>
              {i ? ", " : ""}
              <button type="button" className="font-semibold underline" onClick={() => onOpen(c.id)}>
                “{c.label}”
              </button>
            </span>
          ))}
        </div>
      ) : null}
      <ol className="flex flex-col gap-2">
        {[...history.revisions].reverse().map((r) => (
          <li key={r.revision} className="rounded-md border border-line px-2.5 py-2" data-action={r.action}>
            <div className="flex items-center justify-between gap-2 text-xs">
              <span className="font-semibold">
                {ACTION[r.action]} <span className="font-mono font-normal text-ink-3">rev {r.revision}</span>
              </span>
              <SourceBadge source={r.snapshot.source as "auto" | "human" | "auto_corrected"} />
            </div>
            <div className="text-[11px] text-ink-3">
              {r.actor?.name ?? "A model"} · {new Date(r.created_at).toLocaleString()}
            </div>
            {Object.keys(r.changes).length && r.action !== "deleted" && r.action !== "restored" ? (
              <dl className="mt-1.5 grid grid-cols-[auto_minmax(0,1fr)] gap-x-2 gap-y-0.5 text-[11px]">
                {Object.entries(r.changes).map(([field, change]) => {
                  const c = change as { from?: unknown; to?: unknown };
                  return (
                    <div key={field} className="contents">
                      <dt className="text-ink-3">{field.replace("_", " ")}</dt>
                      <dd className="truncate font-mono">
                        {show(c.from)} → {show(c.to)}
                      </dd>
                    </div>
                  );
                })}
              </dl>
            ) : null}
          </li>
        ))}
      </ol>
    </div>
  );
}
