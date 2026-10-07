import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { HandRunView } from "@/components/cv/HandRunView";
import { RunStatusRefresher } from "@/components/cv/RunStatusRefresher";
import { PageHeader, StatCard, StatusBadge } from "@/components/ui";
import { ErrorPanel } from "@/components/ui/ErrorPanel";
import { KeyValues } from "@/components/ui/KeyValues";
import { Panel } from "@/components/ui/Panel";
import { api } from "@/lib/api/client";
import { requireSession } from "@/lib/auth/session";
import { formatDateTime } from "@/lib/format";

export const metadata: Metadata = { title: "Hand tracking run" };

const fmt = new Intl.NumberFormat("en-US");

export default async function HandRunPage({ params }: PageProps<"/cv/hands/[runId]">) {
  const { runId } = await params;
  const session = await requireSession(`/cv/hands/${runId}`);
  if (!session) return null;
  const res = await api.cvRun(session.token, runId);
  if (!res.ok && res.kind === "http" && (res.status === 404 || res.status === 422)) notFound();
  if (!res.ok) return <ErrorPanel title="Run couldn't be loaded" message={res.message} />;
  const run = res.data;
  const video = await api.video(session.token, run.video.id);
  const done = run.status === "succeeded";
  const rate = done && run.frames_processed ? run.frames_with_hands / run.frames_processed : null;

  return (
    <div className="flex max-w-[1760px] flex-col gap-5">
      <RunStatusRefresher status={run.status} />
      <div className="flex flex-col gap-1">
        <div className="text-xs text-ink-3">
          <Link href="/cv/hands" className="hover:text-ink">Hand Tracking</Link> /{" "}
          <Link href={`/data/videos/${run.video.id}`} className="hover:text-ink">{run.video.name}</Link>
        </div>
        <PageHeader
          title={run.video.name}
          description={<StatusBadge status={run.status} />}
          actions={
            <>
              <Link href={`/cv/fingers/${run.id}`} className="inline-flex h-[30px] items-center rounded-md border border-line-strong px-3 font-medium hover:bg-hover">Finger tracking</Link>
              <Link href={`/annotation/inspector/${run.video.id}`} className="inline-flex h-[30px] items-center rounded-md bg-ink px-3 font-semibold text-canvas hover:opacity-90">Open in inspector</Link>
            </>
          }
        />
      </div>

      {run.status === "failed" ? <ErrorPanel title="This run failed" message={run.error ?? "Unknown error"} /> : null}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <StatCard label="Frames processed" value={run.frames_processed} hint={run.frames_total ? `of ${fmt.format(run.frames_total)}${run.stride > 1 ? `, every ${run.stride}` : ""}` : undefined} />
        <StatCard label="Frames with a hand" value={rate === null ? null : `${(rate * 100).toFixed(1)}%`} hint={done ? `${fmt.format(run.frames_processed - run.frames_with_hands)} without` : undefined} />
        <StatCard label="Tracks" value={done ? run.tracks : null} hint={done ? `${fmt.format(run.detections)} detections` : undefined} />
        <StatCard label="Missing detections" value={done ? run.missing_detections : null} hint="Frames a live track went undetected" />
        <StatCard label="Tracking failures" value={done ? run.tracking_failures : null} hint="Hand dropped, re-found as a new track" />
        <StatCard label="Mean confidence" value={run.mean_confidence == null ? null : run.mean_confidence.toFixed(3)} hint="From the model" />
      </div>

      {done && video.ok ? (
        <HandRunView run={run} video={video.data} />
      ) : !done ? (
        <Panel title="Output">
          <p className="py-2 text-xs text-ink-3">{run.status === "failed" ? "No output: the run failed." : `Tracking… ${fmt.format(run.frames_processed)} frames so far. This page refreshes on its own.`}</p>
        </Panel>
      ) : null}

      <Panel title="Provenance">
        <KeyValues
          rows={[
            ["Model version", run.model_version ? <span key="m" className="font-mono text-xs">{run.model_version.name} {run.model_version.version}</span> : null],
            ["Adapter", <span key="a" className="font-mono text-xs">{run.adapter}</span>],
            ["Config", <span key="c" className="font-mono text-xs break-all">{Object.keys(run.config).length ? JSON.stringify(run.config) : "defaults"}</span>],
            ["Timing", run.stats.exact_timing === false ? "Nominal FPS (no frame index)" : "Frame index (exact)"],
            ["Stored rows", done ? `${fmt.format(run.output_rows.hands ?? 0)} hand rows, ${fmt.format(run.output_rows.fingers ?? 0)} finger rows (Parquet)` : null],
            ["Started", run.started_at ? formatDateTime(run.started_at) : null],
            ["Finished", run.finished_at ? formatDateTime(run.finished_at) : null],
            ["Job", run.job_id ? <span key="j" className="font-mono text-xs">{run.job_id}</span> : null],
          ]}
        />
      </Panel>
    </div>
  );
}
