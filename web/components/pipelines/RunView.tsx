"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { StatusBadge } from "@/components/ui";
import { browserApi } from "@/lib/api/browser";
import type { Page, RunDetail, StepRead, StepTypeRead } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { formatDateTime } from "@/lib/format";
import {
  asGraph,
  completeLayout,
  formatDuration,
  overall,
  PROGRESS_ORDER,
  resultLinks,
  STEP_LABEL,
  STEP_TONE,
  stepCount,
  type Layout,
} from "@/lib/pipelines";
import { Canvas, type NodeInfo, type NodeStatus } from "./Canvas";
import { LogPanel, type LogFilter } from "./LogPanel";
import { DownloadAnnotated } from "./DownloadAnnotated";
import { ProgressBar } from "./ProgressBar";

function nodeStatus(counts: Record<string, number>, perVideo: boolean): NodeStatus {
  const o = overall(counts);
  const { done, total } = stepCount(counts);
  const n = (s: string) => counts[s] ?? 0;
  const parts = [perVideo ? `${done}/${total} videos` : STEP_LABEL[o === "empty" ? "pending" : o]];
  if (n("failed")) parts.push(`${n("failed")} failed`);
  if (n("running")) parts.push(`${n("running")} running`);
  if (n("retry_wait")) parts.push(`${n("retry_wait")} retrying`);
  if (n("skipped")) parts.push(`${n("skipped")} skipped`);
  const tone: NodeStatus["tone"] = o === "failed" ? "error" : o === "running" || o === "queued" ? "running" : o === "retry_wait" ? "warning"
    : o === "succeeded" ? "success" : "neutral";
  return { tone, text: parts.join(" · ") };
}

const btn = "inline-flex h-[30px] items-center rounded-md border border-line-strong px-3 text-xs font-medium hover:bg-hover disabled:opacity-50";

/**
 * A run: the graph with how each step is doing, every step (per video) with its attempts, duration, and
 * failure reason, and the run's logs. Failed steps can be retried one by one or all at once; steps that
 * finished are never run again. Updates itself while the run is going.
 */
export function RunView({ initial, initialSteps, steps: catalog, canEdit }: {
  initial: RunDetail;
  initialSteps: Page<StepRead>;
  steps: StepTypeRead[];
  canEdit: boolean;
}) {
  const router = useRouter();
  const [run, setRun] = useState(initial);
  const [steps, setSteps] = useState(initialSteps);
  const [node, setNode] = useState<string | null>(null);
  const [status, setStatus] = useState<string>("");
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [logFilter, setLogFilter] = useState<LogFilter>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const live = run.status === "running";

  const info = useMemo(
    () => Object.fromEntries(catalog.map((s) => [s.key, { label: s.label, category: s.category, perVideo: s.per_video }])) as Record<string, NodeInfo>,
    [catalog],
  );
  const graph = useMemo(() => asGraph(run.graph), [run.graph]);
  const layout = useMemo(() => completeLayout(graph, run.layout as Layout, catalog.map((s) => s.key)), [graph, run.layout, catalog]);
  const nodeStatuses = useMemo(
    () => Object.fromEntries(run.nodes.map((n) => [n.node_id, nodeStatus(n.counts, n.per_video)])),
    [run.nodes],
  );

  const refresh = async () => {
    const q = new URLSearchParams({ limit: "500" });
    if (node) q.set("node_id", node);
    if (status) q.set("status", status);
    const [r, s] = await Promise.all([
      browserApi<RunDetail>(`/pipelines/runs/${run.id}`),
      browserApi<Page<StepRead>>(`/pipelines/runs/${run.id}/steps`, { query: q }),
    ]);
    if (r.ok) setRun(r.data);
    if (s.ok) setSteps(s.data);
  };
  useEffect(() => {
    void refresh(); // eslint-disable-line react-hooks/set-state-in-effect -- refetches when the filters change
  }, [node, status]); // eslint-disable-line react-hooks/exhaustive-deps
  const latest = useRef(refresh);
  useEffect(() => {
    latest.current = refresh;
  });
  useEffect(() => {
    if (!live) return;
    const t = setInterval(() => void latest.current(), 2000);
    return () => clearInterval(t);
  }, [live]);

  const act = async (path: string, body?: unknown) => {
    setBusy(true);
    setError(null);
    const res = await browserApi<unknown>(path, { method: "POST", body: body ?? {} });
    setBusy(false);
    if (!res.ok) setError(res.message);
    await refresh();
    router.refresh();
  };

  const failed = run.counts.failed ?? 0;
  const retryWait = run.counts.retry_wait ?? 0;
  const outputs = steps.items.filter((s) => s.status === "succeeded" && (s.result.annotated_video_id || s.step_type === "dataset_build" || s.step_type === "export"));

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-canvas p-3 text-xs" data-testid="run-summary">
        <StatusBadge status={run.status} />
        <span>v{run.version} · {run.trigger === "schedule" ? "scheduled" : run.trigger === "upload" ? "started by a new upload" : "started by hand"} · {run.inputs_label} → {run.video_count} video{run.video_count === 1 ? "" : "s"}</span>
        <span className="text-ink-3">started {run.started_at ? formatDateTime(run.started_at) : "—"} · {formatDuration(run.duration_s)}</span>
        <ProgressBar counts={run.counts} className="w-40" />
        <span className="text-ink-3">{stepCount(run.counts).done}/{stepCount(run.counts).total} steps done</span>
        <span className="ml-auto flex flex-wrap gap-2">
          {canEdit && (failed || retryWait) ? (
            <button type="button" className={cn(btn, "border-accent text-accent")} disabled={busy} onClick={() => act(`/pipelines/runs/${run.id}/retry`)}>
              Retry {failed + retryWait} failed step{failed + retryWait === 1 ? "" : "s"}
            </button>
          ) : null}
          {canEdit && live ? <button type="button" className={btn} disabled={busy} onClick={() => act(`/pipelines/runs/${run.id}/cancel`)}>Cancel run</button> : null}
          <Link href={`/pipelines/builder?id=${run.pipeline.id}`} className={btn}>Open in builder</Link>
        </span>
      </div>
      {run.error ? <p className="rounded-md border border-error-line bg-error-bg px-3 py-1.5 text-xs text-error">{run.error}</p> : null}
      {error ? <p role="alert" className="rounded-md border border-error-line bg-error-bg px-3 py-1.5 text-xs text-error">{error}</p> : null}

      <Canvas graph={graph} layout={layout} info={info} status={nodeStatuses} selected={node}
              onSelect={(id) => setNode((cur) => (cur === id ? null : id))} label="Run graph" />

      {outputs.length ? (
        <section aria-label="Outputs" className="flex flex-wrap gap-2 rounded-lg border border-line bg-canvas p-3 text-xs">
          <h2 className="w-full text-[13px] font-semibold">Outputs</h2>
          {outputs.map((s) => s.result.annotated_video_id ? (
            <DownloadAnnotated key={s.id} id={String(s.result.annotated_video_id)} label={`Annotated video · ${s.video?.name ?? ""}`} />
          ) : (
            resultLinks(s.step_type, s.result).map((l) => (
              <Link key={s.id + l.href} href={l.href} className="rounded-md border border-line-strong px-2.5 py-1 font-medium hover:bg-hover">
                {s.step_type === "export" ? `Exports of ${String(s.result.dataset_version_id ?? "").slice(0, 8)}` : `Dataset ${String(s.result.dataset ?? "")} ${l.label}`}
              </Link>
            ))
          ))}
        </section>
      ) : null}

      <section aria-label="Steps" className="flex min-w-0 flex-col gap-2 rounded-lg border border-line bg-canvas p-3 text-xs">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="mr-auto text-[13px] font-semibold">Steps</h2>
          <label htmlFor="step-node" className="text-ink-2">Step</label>
          <select id="step-node" value={node ?? ""} onChange={(e) => setNode(e.target.value || null)} className="h-[28px] rounded-md border border-line-strong bg-canvas px-2">
            <option value="">All steps</option>
            {run.nodes.map((n) => <option key={n.node_id} value={n.node_id}>{n.label} ({n.node_id})</option>)}
          </select>
          <label htmlFor="step-status" className="text-ink-2">Status</label>
          <select id="step-status" value={status} onChange={(e) => setStatus(e.target.value)} className="h-[28px] rounded-md border border-line-strong bg-canvas px-2">
            <option value="">Any</option>
            {PROGRESS_ORDER.map((s) => <option key={s} value={s}>{STEP_LABEL[s]}</option>)}
          </select>
          <span className="text-ink-3">{steps.total} step{steps.total === 1 ? "" : "s"}</span>
        </div>
        <div className="relative overflow-x-auto rounded-md border border-line">
          <table className="w-full min-w-[900px]" data-testid="steps">
            <thead className="bg-subtle text-left text-ink-3">
              <tr>
                <th className="px-3 py-2 font-semibold">Step</th><th className="font-semibold">Video</th><th className="font-semibold">Status</th>
                <th className="font-semibold">Attempts</th><th className="font-semibold">Duration</th><th className="font-semibold">Failure reason / result</th>
                <th className="pr-3 text-right font-semibold"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {steps.items.map((s) => {
                const expanded = open.has(s.id);
                return (
                  <Fragment key={s.id}>
                    <tr className="border-t border-line align-top hover:bg-hover" data-step={s.id} data-node={s.node_id} data-status={s.status}>
                      <td className="px-3 py-2">
                        <button type="button" aria-expanded={expanded} onClick={() => setOpen((o) => { const n = new Set(o); if (n.has(s.id)) n.delete(s.id); else n.add(s.id); return n; })}
                                className="text-left font-semibold hover:underline">{expanded ? "▾" : "▸"} {s.label}</button>
                        <div className="font-mono text-[10px] text-ink-3">{s.node_id}</div>
                      </td>
                      <td className="py-2">{s.video ? <Link href={`/data/videos/${s.video.id}`} className="hover:underline">{s.video.name}</Link> : <span className="text-ink-3">whole run</span>}</td>
                      <td className="py-2"><StatusBadge status={STEP_TONE[s.status]} label={STEP_LABEL[s.status]} />
                        {s.status === "retry_wait" && s.retry_at ? <div className="text-ink-3">at {new Date(s.retry_at).toLocaleTimeString()}</div> : null}</td>
                      <td className="py-2 tabular-nums">{s.attempts}{s.max_attempts > 1 ? <span className="text-ink-3"> of {s.max_attempts}</span> : null}</td>
                      <td className="py-2 tabular-nums">{formatDuration(s.duration_s)}</td>
                      <td className="max-w-[420px] py-2">
                        {s.error ? (
                          <div className={s.status === "skipped" ? "text-ink-2" : "text-error"}>
                            {s.error_label ? <b>{s.error_label}: </b> : null}<span className="break-words">{s.error}</span>
                          </div>
                        ) : (
                          <div className="flex flex-wrap gap-1.5">
                            {resultLinks(s.step_type, s.result).map((l) => <Link key={l.href} href={l.href} className="underline">{l.label}</Link>)}
                            {s.result.annotated_video_id ? <DownloadAnnotated id={String(s.result.annotated_video_id)} label="Download video" small /> : null}
                            {typeof s.result.flagged === "boolean" ? (
                              <span className={s.result.flagged ? "text-warning" : "text-success"}>{s.result.flagged ? `flagged ${String(s.result.flag)}` : "passed"}</span>
                            ) : null}
                          </div>
                        )}
                      </td>
                      <td className="py-2 pr-3 text-right">
                        <span className="inline-flex gap-1.5">
                          <button type="button" className="rounded-md border border-line px-2 py-0.5 hover:bg-canvas"
                                  onClick={() => setLogFilter({ stepRunId: s.id, label: `${s.label}${s.video ? ` · ${s.video.name}` : ""}` })}>Logs</button>
                          {canEdit && (s.status === "failed" || s.status === "retry_wait") ? (
                            <button type="button" disabled={busy} className="rounded-md border border-accent px-2 py-0.5 font-semibold text-accent hover:bg-accent-soft"
                                    onClick={() => act(`/pipelines/runs/${run.id}/retry`, { step_ids: [s.id] })}>Retry</button>
                          ) : null}
                        </span>
                      </td>
                    </tr>
                    {expanded ? (
                      <tr className="bg-subtle">
                        <td colSpan={7} className="px-3 py-2">
                          <ol className="flex flex-col gap-1">
                            {(s.attempt_list ?? []).map((a) => (
                              <li key={a.id} className="flex flex-wrap items-baseline gap-2">
                                <span className="font-semibold">Attempt {a.number}</span>
                                <StatusBadge status={STEP_TONE[a.status]} label={STEP_LABEL[a.status]} />
                                <span className="text-ink-3">{a.reason.replace("_", " ")} · {a.started_at ? formatDateTime(a.started_at) : "not started"}
                                  {a.started_at && a.finished_at ? ` · ${formatDuration((new Date(a.finished_at).getTime() - new Date(a.started_at).getTime()) / 1000)}` : ""}</span>
                                {a.error ? <span className="break-words text-error">{a.error}</span> : null}
                                {a.job_id ? <span className="font-mono text-[10px] text-ink-3">job {a.job_id.slice(0, 8)}</span> : null}
                              </li>
                            ))}
                            {!(s.attempt_list ?? []).length ? <li className="text-ink-3">Not started: waiting for the steps before it.</li> : null}
                          </ol>
                          {Object.keys(s.result).length ? (
                            <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-all rounded bg-canvas p-2 font-mono text-[10.5px] text-ink-2">{JSON.stringify(s.result, null, 2)}</pre>
                          ) : null}
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                );
              })}
              {!steps.items.length ? <tr><td colSpan={7} className="px-3 py-6 text-center text-ink-3">No steps match.</td></tr> : null}
            </tbody>
          </table>
        </div>
      </section>

      <LogPanel runId={run.id} live={live} filter={logFilter.stepRunId ? logFilter : node ? { nodeId: node, label: `Step ${node}` } : {}}
                onClearFilter={() => { setLogFilter({}); setNode(null); }} />
    </div>
  );
}
