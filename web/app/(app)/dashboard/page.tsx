import { Activity, ArrowUp, Unplug } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { PipelineLevels } from "@/components/overview/PipelineLevels";
import { PipelineRuns } from "@/components/overview/PipelineRuns";
import { RecentJobs } from "@/components/overview/RecentJobs";
import { EmptyState, StatCard } from "@/components/ui";
import { api, apiUrl } from "@/lib/api/client";
import { requireSession } from "@/lib/auth/session";
import { cn } from "@/lib/cn";
import { formatDateTime } from "@/lib/format";
import { pipelineCounts } from "@/lib/pipelineCounts";

export const metadata: Metadata = { title: "Overview" };

export default async function OverviewPage() {
  const session = await requireSession("/dashboard");
  if (!session) return null; // the layout shows the API-unavailable state
  const [res, counts, runs] = await Promise.all([
    api.overview(session.token),
    pipelineCounts(session.token),
    api.pipelineRuns(session.token, { limit: 4 }),
  ]);
  const data = res.ok ? res.data : null;
  const { user } = session;
  const firstName = (user.name || user.email.split("@")[0]).split(" ")[0];

  return (
    <div className="flex w-full max-w-[1840px] flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-col gap-1">
          <div className="font-mono text-xs text-ink-3">Overview</div>
          <h1 className="text-4xl font-extrabold tracking-[-0.035em] text-balance md:text-5xl">
            Welcome back, <span className="text-accent">{firstName}</span>.
          </h1>
        </div>
        {user.role !== "viewer" ? (
          <Link
            href="/data/upload"
            className="flex h-11 items-center gap-2 rounded-full bg-ink px-5 font-bold text-ground hover:opacity-90"
          >
            <ArrowUp className="size-4" aria-hidden />
            Upload videos
          </Link>
        ) : null}
      </div>

      {!res.ok ? (
        <section className="rounded-2xl border border-warning-line bg-warning-bg">
          <EmptyState
            size="compact"
            icon={<Unplug className="size-5 text-warning" aria-hidden />}
            title={res.kind === "unreachable" ? "Can't reach the Ego Labs API" : "The overview couldn't be loaded"}
            description={
              <>
                Tried <code className="rounded border border-line bg-canvas px-1 font-mono text-xs">{apiUrl()}/api/v1/overview</code>{" "}
                ({res.message}). Start the stack with{" "}
                <code className="rounded border border-line bg-canvas px-1 font-mono text-xs">docker compose up</code> or set{" "}
                <code className="rounded border border-line bg-canvas px-1 font-mono text-xs">API_URL</code>. Numbers stay
                blank until real data is available.
              </>
            }
          />
        </section>
      ) : null}

      <PipelineLevels counts={counts} />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard size="lg" label="Datasets" value={data?.counts.datasets ?? null} href="/datasets/versions" />
        <StatCard size="lg" label="Sessions" value={data?.counts.sessions ?? null} href="/data/sessions" />
        <StatCard size="lg" label="Videos" value={data?.counts.videos ?? null} href="/data/videos" />
        <StatCard
          size="lg"
          tone={data && data.counts.jobs_active > 0 ? "accent" : "default"}
          label="Active jobs"
          value={data?.counts.jobs_active ?? null}
          href="/pipelines/runs"
        />
      </div>

      <PipelineRuns runs={runs.ok ? runs.data.items : []} unavailable={!runs.ok} />

      <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <RecentJobs jobs={data?.recent_jobs ?? []} unavailable={!res.ok} />

        <section aria-labelledby="activity-title" className="flex min-w-0 flex-col gap-4 rounded-3xl bg-ink p-5 text-ground">
          <h2 id="activity-title" className="text-lg font-extrabold tracking-tight">
            Activity
          </h2>
          {data && data.recent_events.length > 0 ? (
            <ol className="flex flex-col">
              {data.recent_events.map((e, i) => (
                <li key={e.id} className="relative flex gap-3 pb-4 last:pb-0">
                  {i < data.recent_events.length - 1 ? (
                    <span aria-hidden className="absolute bottom-0 left-[4.5px] top-3 w-px bg-ground/20" />
                  ) : null}
                  <span
                    aria-hidden
                    className={cn("relative mt-1.5 size-2.5 flex-none rounded-full", i === 0 ? "bg-accent" : "border-2 border-ground/60 bg-ink")}
                  />
                  <div className="min-w-0">
                    <div className="font-semibold">{e.message}</div>
                    <div className="text-xs text-ground/70">
                      <span className="font-mono">{e.type}</span> · {formatDateTime(e.created_at)}
                    </div>
                  </div>
                </li>
              ))}
            </ol>
          ) : (
            <div role="status" className="flex flex-col items-center gap-1 px-4 py-6 text-center">
              <Activity className="mb-1 size-4 text-ground/70" aria-hidden />
              <div className="font-semibold">{data ? "No activity yet" : "Activity unavailable"}</div>
              <div className="text-ground/80">
                {data ? "Uploads, processing runs, and reviews show up here." : "Connect the API to see the activity stream."}
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
