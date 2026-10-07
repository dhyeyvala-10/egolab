"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { browserApi } from "@/lib/api/browser";
import type { RunLogLine, RunLogPage } from "@/lib/api/types";
import { cn } from "@/lib/cn";

const LEVELS = ["debug", "info", "warning", "error"] as const;
const LEVEL_CLASS: Record<string, string> = {
  debug: "text-ink-3",
  info: "text-ink-2",
  warning: "text-warning",
  error: "text-error font-semibold",
};

export interface LogFilter {
  nodeId?: string | null;
  stepRunId?: string | null;
  label?: string;
}

function time(ts: string) {
  const d = new Date(ts);
  return `${d.toISOString().slice(11, 19)}.${String(d.getMilliseconds()).padStart(3, "0")}`;
}

/**
 * A run's complete log (the engine's lines and every attempt's job log), searched on the server: any word
 * or fragment of a message or its data, by level, and narrowed to one step. While the run is going, new
 * lines are fetched as they arrive.
 */
export function LogPanel({ runId, live, filter, onClearFilter }: {
  runId: string;
  live: boolean;
  filter: LogFilter;
  onClearFilter: () => void;
}) {
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [levels, setLevels] = useState<string[]>([]);
  const [lines, setLines] = useState<RunLogLine[]>([]);
  const [meta, setMeta] = useState<{ matched: number; total: number; more: boolean }>({ matched: 0, total: 0, more: false });
  const [open, setOpen] = useState<Set<number>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const last = useRef(0);

  const params = useCallback((after: number) => {
    const p = new URLSearchParams({ limit: "300", after_id: String(after) });
    if (query) p.set("q", query);
    levels.forEach((l) => p.append("level", l));
    if (filter.stepRunId) p.set("step_run_id", filter.stepRunId);
    else if (filter.nodeId) p.set("node_id", filter.nodeId);
    return p;
  }, [query, levels, filter.nodeId, filter.stepRunId]);

  const load = useCallback(async (after: number, append: boolean) => {
    const res = await browserApi<RunLogPage>(`/pipelines/runs/${runId}/logs`, { query: params(after) });
    if (!res.ok) {
      setError(res.message);
      return;
    }
    setError(null);
    setLines((prev) => (append ? [...prev, ...res.data.items] : res.data.items));
    if (res.data.items.length) last.current = res.data.items[res.data.items.length - 1].id;
    else if (!append) last.current = 0;
    setMeta({ matched: res.data.matched, total: res.data.total, more: res.data.next_after_id !== null });
  }, [runId, params]);

  useEffect(() => {
    last.current = 0;
    void load(0, false); // eslint-disable-line react-hooks/set-state-in-effect -- fetches, then sets state
  }, [load]);
  useEffect(() => {
    if (!live) return;
    const t = setInterval(() => void load(last.current, true), 2000);
    return () => clearInterval(t);
  }, [live, load]);

  const toggle = (id: number) => setOpen((s) => {
    const n = new Set(s);
    if (n.has(id)) n.delete(id);
    else n.add(id);
    return n;
  });

  return (
    <section aria-label="Run logs" className="flex min-w-0 flex-col gap-2 rounded-lg border border-line bg-canvas p-3 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="mr-auto text-[13px] font-semibold">Logs</h2>
        <form className="flex items-center gap-1.5" onSubmit={(e) => { e.preventDefault(); setQuery(q.trim()); }} role="search">
          <label htmlFor="log-q" className="sr-only">Search the logs</label>
          <input id="log-q" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search messages and data…"
                 className="h-[28px] w-56 rounded-md border border-line-strong bg-canvas px-2" />
          <button type="submit" className="h-[28px] rounded-md border border-line-strong px-2.5 font-medium hover:bg-hover">Search</button>
          {query ? <button type="button" onClick={() => { setQ(""); setQuery(""); }} className="text-ink-3 hover:underline">Clear</button> : null}
        </form>
        <div className="flex items-center gap-1" role="group" aria-label="Levels">
          {LEVELS.map((l) => {
            const on = levels.includes(l);
            return (
              <button key={l} type="button" aria-pressed={on} onClick={() => setLevels(on ? levels.filter((x) => x !== l) : [...levels, l])}
                      className={cn("h-[26px] rounded-full border px-2 capitalize", on ? "border-ink bg-ink text-canvas" : "border-line hover:bg-hover")}>
                {l}
              </button>
            );
          })}
        </div>
        <a href={`/api/v1/pipelines/runs/${runId}/logs.txt${query ? `?q=${encodeURIComponent(query)}` : ""}`}
           className="h-[26px] rounded-md border border-line-strong px-2 leading-[24px] hover:bg-hover">Download .log</a>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-ink-3" data-testid="log-meta">
        <span>{meta.matched === meta.total ? `${meta.total} lines` : `${meta.matched} of ${meta.total} lines match`}</span>
        {filter.label ? (
          <span className="flex items-center gap-1 rounded-full border border-accent bg-accent-soft px-2 py-0.5 text-ink">
            {filter.label}
            <button type="button" aria-label="Show all steps" onClick={onClearFilter} className="font-bold">×</button>
          </span>
        ) : null}
        {live ? <span className="text-running">● live</span> : null}
      </div>
      {error ? <p role="alert" className="text-error">{error}</p> : null}
      <ol className="max-h-[520px] overflow-auto rounded-md border border-line bg-subtle font-mono text-[11px] leading-5" data-testid="log-lines">
        {lines.map((l) => {
          const hasData = Object.keys(l.data ?? {}).length > 0;
          return (
            <li key={l.id} className="border-b border-line/60 px-2 py-0.5 last:border-b-0">
              <div className="flex min-w-0 flex-wrap items-baseline gap-x-2">
                <span className="text-ink-3">{time(l.ts)}</span>
                <span className={cn("w-14 uppercase", LEVEL_CLASS[l.level])}>{l.level}</span>
                <span className="text-accent">[{l.source}{l.attempt ? ` #${l.attempt}` : ""}{l.video ? ` · ${l.video.name}` : ""}]</span>
                <span className="min-w-0 break-words font-sans text-[12px] text-ink">{l.message}</span>
                {hasData ? (
                  <button type="button" onClick={() => toggle(l.id)} className="text-ink-3 hover:underline" aria-expanded={open.has(l.id)}>
                    {open.has(l.id) ? "hide data" : "data"}
                  </button>
                ) : null}
              </div>
              {hasData && open.has(l.id) ? (
                <pre className="mt-0.5 max-w-full overflow-auto whitespace-pre-wrap break-all rounded bg-canvas p-1.5 text-[10.5px] text-ink-2">
                  {JSON.stringify(l.data, null, 2)}
                </pre>
              ) : null}
            </li>
          );
        })}
        {!lines.length ? <li className="px-2 py-4 text-center font-sans text-ink-3">{query || levels.length ? "No lines match." : "No log lines yet."}</li> : null}
      </ol>
      {meta.more ? (
        <button type="button" onClick={() => void load(last.current, true)} className="self-start rounded-md border border-line-strong px-2.5 py-1 font-medium hover:bg-hover">
          Load more
        </button>
      ) : null}
    </section>
  );
}
