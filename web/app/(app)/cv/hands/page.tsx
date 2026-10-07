import type { Metadata } from "next";
import { AdapterPanel } from "@/components/cv/AdapterPanel";
import { RunTable } from "@/components/cv/RunTable";
import { StartRunForm } from "@/components/cv/StartRunForm";
import { PageHeader } from "@/components/ui";
import { ErrorPanel } from "@/components/ui/ErrorPanel";
import { Panel } from "@/components/ui/Panel";
import { api } from "@/lib/api/client";
import { requireSession } from "@/lib/auth/session";
import { pickQuery } from "@/lib/query";

export const metadata: Metadata = { title: "Hand Tracking" };

export default async function HandTrackingPage({ searchParams }: PageProps<"/cv/hands">) {
  const session = await requireSession("/cv/hands");
  if (!session) return null;
  const query = pickQuery(await searchParams, ["status", "offset"]);
  const canRun = session.user.role !== "viewer";
  const [runs, adapter, videos] = await Promise.all([
    api.cvRuns(session.token, { ...query, kind: "hand_tracking", limit: 50 }),
    api.cvAdapter(session.token),
    canRun ? api.videos(session.token, { status: "ready", limit: 200 }) : null,
  ]);

  return (
    <div className="flex max-w-[1760px] flex-col gap-5">
      <PageHeader
        eyebrow="Computer Vision"
        title="Hand Tracking"
        description="21-keypoint hand tracking with persistent track IDs, smoothed and stored per frame. Every output references the model version that produced it."
      />
      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        {canRun ? (
          <Panel title="Run hand tracking" hint="Object detection and movement classification follow by default">
            {videos?.ok ? (
              <StartRunForm videos={videos.data.items.map((v) => ({ id: v.id, name: v.original_filename }))} disabled={adapter.ok && !adapter.data.runnable ? adapter.data.error : null} verb="Run" />
            ) : (
              <p className="text-xs text-error">Couldn&apos;t load videos.</p>
            )}
          </Panel>
        ) : null}
        {adapter.ok ? <AdapterPanel info={adapter.data} /> : <ErrorPanel title="Model configuration couldn't be loaded" message={adapter.message} />}
      </div>
      {runs.ok ? <RunTable page={runs.data} query={query} base="/cv/hands" kind="hand_tracking" /> : <ErrorPanel title="Runs couldn't be loaded" message={runs.message} />}
    </div>
  );
}
