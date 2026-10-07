import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ObjectRunView } from "@/components/cv/ObjectRunView";
import { RunStatusRefresher } from "@/components/cv/RunStatusRefresher";
import { PageHeader, StatCard, StatusBadge } from "@/components/ui";
import { ErrorPanel } from "@/components/ui/ErrorPanel";
import { KeyValues } from "@/components/ui/KeyValues";
import { Panel } from "@/components/ui/Panel";
import { api } from "@/lib/api/client";
import { requireSession } from "@/lib/auth/session";
import { formatDateTime } from "@/lib/format";

export const metadata: Metadata = { title: "Object detection run" };

const fmt = new Intl.NumberFormat("en-US");

interface LabelStats {
  tracks: number;
  detections: number;
  mean_score: number;
}

export default async function ObjectRunPage({ params }: PageProps<"/cv/objects/[runId]">) {
  const { runId } = await params;
  const session = await requireSession(`/cv/objects/${runId}`);
  if (!session) return null;
  const res = await api.cvRun(session.token, runId);
  if (!res.ok && res.kind === "http" && (res.status === 404 || res.status === 422)) notFound();
  if (!res.ok) return <ErrorPanel title="Run couldn't be loaded" message={res.message} />;
  const run = res.data;
  if (run.kind !== "object_detection") notFound();
  const [video, hands] = await Promise.all([
    api.video(session.token, run.video.id),
    api.cvRuns(session.token, { video_id: run.video.id, kind: "hand_tracking", status: "succeeded", limit: 1 }),
  ]);
  const handRunId = hands.ok ? (hands.data.items[0]?.id ?? null) : null;
  const done = run.status === "succeeded";
  const labels = Object.entries((run.stats.labels ?? {}) as Record<string, LabelStats>).sort((a, b) => b[1].detections - a[1].detections);
  const withObjects = (run.stats.frames_with_objects as number | undefined) ?? null;

  return (
    <div className="flex max-w-[1760px] flex-col gap-5">
      <RunStatusRefresher status={run.status} />
      <div className="flex flex-col gap-1">
        <div className="text-xs text-ink-3">
          <Link href="/cv/objects" className="hover:text-ink">Object Tracking</Link> /{" "}
          <Link href={`/data/videos/${run.video.id}`} className="hover:text-ink">{run.video.name}</Link>
        </div>
        <PageHeader
          title={run.video.name}
          description={<StatusBadge status={run.status} />}
          actions={<Link href={`/annotation/inspector/${run.video.id}`} className="inline-flex h-[30px] items-center rounded-md bg-ink px-3 font-semibold text-canvas hover:opacity-90">Open in inspector</Link>}
        />
      </div>
      {run.status === "failed" ? <ErrorPanel title="This run failed" message={run.error ?? "Unknown error"} /> : null}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard label="Frames processed" value={run.frames_processed} hint={run.frames_total ? `of ${fmt.format(run.frames_total)}${run.stride > 1 ? `, every ${run.stride}` : ""}` : undefined} />
        <StatCard label="Frames with an object" value={done && withObjects != null && run.frames_processed ? `${((withObjects / run.frames_processed) * 100).toFixed(1)}%` : null} />
        <StatCard label="Objects" value={done ? run.tracks : null} hint={done ? `${fmt.format(run.detections)} detections` : undefined} />
        <StatCard label="Missing detections" value={done ? run.missing_detections : null} hint="Frames a live track went unseen (often hidden by a hand)" />
      </div>
      {done && video.ok ? (
        <ObjectRunView run={run} video={video.data} handRunId={handRunId} />
      ) : !done ? (
        <Panel title="Output">
          <p className="py-2 text-xs text-ink-3">{run.status === "failed" ? "No output: the run failed." : `Detecting… ${fmt.format(run.frames_processed)} frames so far. This page refreshes on its own.`}</p>
        </Panel>
      ) : null}
      <div className="grid items-start gap-4 lg:grid-cols-2">
        <Panel title="Labels" hint="Per detector label">
          {labels.length ? (
            <table className="w-full text-xs">
              <thead><tr className="text-left text-ink-3"><th className="py-1 font-semibold">Label</th><th className="py-1 text-right font-semibold">Tracks</th><th className="py-1 text-right font-semibold">Detections</th><th className="py-1 text-right font-semibold">Mean score</th></tr></thead>
              <tbody>
                {labels.map(([label, s]) => (
                  <tr key={label} className="border-t border-line"><td className="py-1">{label}</td><td className="py-1 text-right tabular-nums">{s.tracks}</td><td className="py-1 text-right tabular-nums">{fmt.format(s.detections)}</td><td className="py-1 text-right tabular-nums">{s.mean_score.toFixed(2)}</td></tr>
                ))}
              </tbody>
            </table>
          ) : <p className="py-2 text-xs text-ink-3">{done ? "Nothing detected." : "Available when the run succeeds."}</p>}
        </Panel>
        <Panel title="Provenance">
          <KeyValues
            rows={[
              ["Model version", run.model_version ? <span key="m" className="font-mono text-xs">{run.model_version.name} {run.model_version.version}</span> : null],
              ["Adapter", <span key="a" className="font-mono text-xs">{run.adapter}</span>],
              ["Config", <span key="c" className="font-mono text-xs break-all">{Object.keys(run.config).length ? JSON.stringify(run.config) : "defaults"}</span>],
              ["Stored rows", done ? `${fmt.format(run.output_rows.objects ?? 0)} object boxes (Parquet)` : null],
              ["Started", run.started_at ? formatDateTime(run.started_at) : null],
              ["Finished", run.finished_at ? formatDateTime(run.finished_at) : null],
              ["Job", run.job_id ? <span key="j" className="font-mono text-xs">{run.job_id}</span> : null],
            ]}
          />
        </Panel>
      </div>
    </div>
  );
}
