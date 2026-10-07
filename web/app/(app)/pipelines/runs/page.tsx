import type { Metadata } from "next";
import Link from "next/link";
import { Refresher } from "@/components/datasets/Refresher";
import { ProgressBar } from "@/components/pipelines/ProgressBar";
import { PageHeader, StatCard, StatusBadge } from "@/components/ui";
import { ErrorPanel } from "@/components/ui/ErrorPanel";
import { api } from "@/lib/api/client";
import { requireSession } from "@/lib/auth/session";
import { formatDateTime } from "@/lib/format";
import { formatDuration, stepCount } from "@/lib/pipelines";
import { pickQuery } from "@/lib/query";

export const metadata: Metadata = { title: "Pipeline runs" };

const STATUSES = ["running", "failed", "succeeded", "cancelled"] as const;

export default async function RunsPage({ searchParams }: PageProps<"/pipelines/runs">) {
  const session = await requireSession("/pipelines/runs");
  if (!session) return null;
  const query = pickQuery(await searchParams, ["pipeline_id", "status", "schedule_id"]);
  const [runs, pipelines, running, failed] = await Promise.all([
    api.pipelineRuns(session.token, { ...query, limit: 100 }),
    api.pipelines(session.token, { limit: 200 }),
    api.pipelineRuns(session.token, { status: "running", limit: 1 }),
    api.pipelineRuns(session.token, { status: "failed", limit: 1 }),
  ]);
  const items = runs.ok ? runs.data.items : [];
  return (
    <div className="flex max-w-[1760px] flex-col gap-5">
      <Refresher active={items.some((r) => r.status === "running")} ms={3000} />
      <PageHeader
        eyebrow="Pipelines"
        title="Runs"
        description="Every pipeline run: its steps' progress, how long it took, and what failed. Open a run for each step's attempts and the run's searchable logs."
        actions={<Link href="/pipelines/builder" className="inline-flex h-[30px] items-center rounded-md bg-ink px-3 text-xs font-semibold text-canvas hover:opacity-90">Build a pipeline</Link>}
      />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard label="Pipelines" value={pipelines.ok ? pipelines.data.total : null} href="/pipelines/builder" />
        <StatCard label="Runs" value={runs.ok ? runs.data.total : null} hint={Object.keys(query).length ? "matching the filters" : undefined} />
        <StatCard label="Running" value={running.ok ? running.data.total : null} href="/pipelines/runs?status=running" tone={running.ok && running.data.total ? "accent" : "default"} />
        <StatCard label="Failed" value={failed.ok ? failed.data.total : null} href="/pipelines/runs?status=failed" />
      </div>
      <form action="/pipelines/runs" className="flex flex-wrap items-center gap-2 text-xs">
        <label htmlFor="pipeline_id" className="text-ink-2">Pipeline</label>
        <select id="pipeline_id" name="pipeline_id" defaultValue={query.pipeline_id ?? ""} className="h-[30px] rounded-md border border-line-strong bg-canvas px-2">
          <option value="">All pipelines</option>
          {pipelines.ok ? pipelines.data.items.map((p) => <option key={p.id} value={p.id}>{p.name}</option>) : null}
        </select>
        <label htmlFor="status" className="text-ink-2">Status</label>
        <select id="status" name="status" defaultValue={query.status ?? ""} className="h-[30px] rounded-md border border-line-strong bg-canvas px-2">
          <option value="">Any</option>
          {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <button type="submit" className="h-[30px] rounded-md border border-line-strong px-3 font-medium hover:bg-hover">Show</button>
      </form>
      {!runs.ok ? <ErrorPanel title="Runs couldn't be loaded" message={runs.message} /> : items.length ? (
        <div className="overflow-x-auto rounded-lg border border-line">
          <table className="w-full min-w-[900px] text-xs" data-testid="runs">
            <thead className="bg-subtle text-left text-ink-3">
              <tr><th className="px-3 py-2 font-semibold">Run</th><th className="font-semibold">Status</th><th className="w-48 font-semibold">Steps</th>
                <th className="text-right font-semibold">Videos</th><th className="pl-4 font-semibold">Input</th><th className="font-semibold">Trigger</th>
                <th className="font-semibold">Started</th><th className="pr-3 text-right font-semibold">Duration</th></tr>
            </thead>
            <tbody>
              {items.map((r) => {
                const { done, total } = stepCount(r.counts);
                return (
                  <tr key={r.id} className="border-t border-line hover:bg-hover" data-run={r.id}>
                    <td className="px-3 py-2"><Link href={`/pipelines/runs/${r.id}`} className="font-semibold hover:underline">{r.pipeline.name} #{r.number}</Link>
                      <div className="text-ink-3">v{r.version}{r.error ? ` · ${r.error}` : ""}</div></td>
                    <td><StatusBadge status={r.status} /></td>
                    <td className="pr-4"><ProgressBar counts={r.counts} /><div className="mt-0.5 text-ink-3">{done}/{total}{r.counts.failed ? ` · ${r.counts.failed} failed` : ""}</div></td>
                    <td className="text-right tabular-nums">{r.video_count}</td>
                    <td className="pl-4 text-ink-2">{r.inputs_label}</td>
                    <td className="text-ink-2">{r.trigger === "schedule" ? "Schedule" : r.trigger === "upload" ? "New upload" : r.created_by?.name ?? "By hand"}</td>
                    <td className="text-ink-2">{r.started_at ? formatDateTime(r.started_at) : "—"}</td>
                    <td className="pr-3 text-right tabular-nums">{formatDuration(r.duration_s)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="rounded-lg border border-dashed border-line-strong py-8 text-center text-xs text-ink-3">
          No runs yet. Build a pipeline (or start from a template) and run it on a session.
        </p>
      )}
    </div>
  );
}
