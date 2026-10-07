import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { FingerCharts } from "@/components/cv/FingerCharts";
import { TrackPicker } from "@/components/cv/TrackPicker";
import { FingerStatsTable, type FingerStat } from "@/components/cv/FingerStatsTable";
import { PageHeader, StatusBadge } from "@/components/ui";
import { ErrorPanel } from "@/components/ui/ErrorPanel";
import { Panel } from "@/components/ui/Panel";
import { api } from "@/lib/api/client";
import { requireSession } from "@/lib/auth/session";
import { FINGERS } from "@/lib/cv/skeleton";

export const metadata: Metadata = { title: "Finger tracking" };

export default async function FingerRunPage({ params, searchParams }: PageProps<"/cv/fingers/[runId]">) {
  const { runId } = await params;
  const session = await requireSession(`/cv/fingers/${runId}`);
  if (!session) return null;
  const res = await api.cvRun(session.token, runId);
  if (!res.ok && res.kind === "http" && (res.status === 404 || res.status === 422)) notFound();
  if (!res.ok) return <ErrorPanel title="Run couldn't be loaded" message={res.message} />;
  const run = res.data;
  const sp = await searchParams;
  const requested = Number(Array.isArray(sp.track) ? sp.track[0] : sp.track);
  const track = run.hand_tracks.find((t) => t.track_id === requested) ?? run.hand_tracks[0];
  const stats = (run.stats.fingers ?? {}) as Record<string, Omit<FingerStat, "finger">>;
  const rows: FingerStat[] = FINGERS.map((f) => ({ finger: f, ...(stats[f] ?? { samples: 0, visibility: null, occluded_rate: null, mean_speed_px_s: null, p95_speed_px_s: null, peak_speed_px_s: null }) }));

  return (
    <div className="flex max-w-[1760px] flex-col gap-5">
      <div className="flex flex-col gap-1">
        <div className="text-xs text-ink-3">
          <Link href="/cv/fingers" className="hover:text-ink">Finger Tracking</Link> / {run.video.name}
        </div>
        <PageHeader
          title={run.video.name}
          description={<StatusBadge status={run.status} />}
          actions={<Link href={`/cv/hands/${run.id}`} className="inline-flex h-[30px] items-center rounded-md border border-line-strong px-3 font-medium hover:bg-hover">Hand tracking &amp; skeletons</Link>}
        />
      </div>
      {run.status !== "succeeded" ? (
        <ErrorPanel title="No finger data yet" message={run.status === "failed" ? (run.error ?? "The run failed") : `The run is ${run.status}.`} />
      ) : !track ? (
        <Panel title="Fingers"><p className="py-2 text-xs text-ink-3">No hands were detected in this video.</p></Panel>
      ) : (
        <>
          <Panel title="Fingertip motion" hint={`Track #${track.track_id} · ${track.handedness} hand · f${track.first_frame}–f${track.last_frame}`}
                 actions={<TrackPicker tracks={run.hand_tracks} current={track.track_id} />}>
            <div className="py-2">
              <FingerCharts runId={run.id} trackId={track.track_id} />
            </div>
          </Panel>
          <Panel title="Per finger, all tracks" hint="Visibility = share of the finger's joints inside the frame; occlusion is estimated from keypoint geometry">
            <FingerStatsTable rows={rows} />
          </Panel>
        </>
      )}
    </div>
  );
}
