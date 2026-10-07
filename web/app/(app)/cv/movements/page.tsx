import type { Metadata } from "next";
import Link from "next/link";
import { AdapterPanel } from "@/components/cv/AdapterPanel";
import { RunTable } from "@/components/cv/RunTable";
import { StartRunForm } from "@/components/cv/StartRunForm";
import { EventTable } from "@/components/movement/EventTable";
import { InteractionGraphView } from "@/components/movement/InteractionGraphView";
import { PageHeader, StatCard } from "@/components/ui";
import { ErrorPanel } from "@/components/ui/ErrorPanel";
import { Panel } from "@/components/ui/Panel";
import { api } from "@/lib/api/client";
import { requireSession } from "@/lib/auth/session";
import { pickQuery } from "@/lib/query";

export const metadata: Metadata = { title: "Movement Classification" };

const EVENT_KEYS = ["video_id", "class", "status", "handedness", "finger", "max_confidence", "sort", "offset"] as const;

export default async function MovementPage({ searchParams }: PageProps<"/cv/movements">) {
  const session = await requireSession("/cv/movements");
  if (!session) return null;
  const params = await searchParams;
  const query = pickQuery(params, EVENT_KEYS);
  const canRun = session.user.role !== "viewer";
  const [events, classes, adapter, videos, runs, review, graph, video] = await Promise.all([
    api.movementEvents(session.token, { ...query, limit: 50 }),
    api.movementClasses(session.token),
    api.cvAdapter(session.token, "movement"),
    api.videos(session.token, { status: "ready", limit: 200 }),
    api.cvRuns(session.token, { kind: "movement", limit: 10 }),
    api.movementEvents(session.token, { status: "needs_review", limit: 1 }),
    query.video_id ? api.movementGraph(session.token, { video_id: query.video_id, limit: 1000 }) : null,
    query.video_id ? api.video(session.token, query.video_id) : null,
  ]);
  const videoRefs = videos.ok ? videos.data.items.map((v) => ({ id: v.id, name: v.original_filename })) : [];
  const active = classes.ok ? classes.data.filter((c) => c.active).length : null;

  return (
    <div className="flex max-w-[1760px] flex-col gap-5">
      <PageHeader
        eyebrow="Computer Vision"
        title="Movement Classification"
        description="Confidence-scored movement events from hand tracking, finger kinematics, and hand–object contact. Each event links back to the exact keypoint frames that produced it."
        actions={<Link href="/cv/movements/classes" className="inline-flex h-[30px] items-center rounded-md border border-line-strong px-3 font-medium hover:bg-hover">Movement classes</Link>}
      />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard label="Events" value={events.ok ? events.data.total : null} hint={query.video_id || Object.keys(query).length ? "matching the filters" : "in each video's latest run"} />
        <StatCard label="Needs review" value={review.ok ? review.data.total : null} hint="Below the review confidence, or flagged" />
        <StatCard label="Active classes" value={active} hint={classes.ok ? `of ${classes.data.length}` : undefined} />
        <StatCard label="Classification runs" value={runs.ok ? runs.data.total : null} />
      </div>
      {events.ok && classes.ok ? (
        <EventTable page={events.data} query={query} classes={classes.data} videos={videoRefs} />
      ) : (
        <ErrorPanel title="Events couldn't be loaded" message={!events.ok ? events.message : !classes.ok ? classes.message : ""} />
      )}
      <Panel title="Interaction graph" hint={graph ? undefined : "Choose a video above to see how its hands, fingers, movements, and objects connect"}>
        {graph ? (
          graph.ok ? <InteractionGraphView graph={graph.data} duration={video?.ok ? (video.data.duration_s ?? 0) : 0} /> : <p className="text-xs text-error">{graph.message}</p>
        ) : (
          <p className="py-2 text-xs text-ink-3">Hand → Finger(s) → Movement → Object → Time range, for one video at a time.</p>
        )}
      </Panel>
      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        {canRun ? (
          <Panel title="Classify again" hint="Uses each video's latest hand and object runs">
            <StartRunForm videos={videoRefs} disabled={adapter.ok && !adapter.data.runnable ? adapter.data.error : null}
                          kinds={[{ kind: "movement", label: "Movement classification", checked: true }]} verb="Classify movements" strides={false} />
          </Panel>
        ) : null}
        {adapter.ok ? <AdapterPanel info={adapter.data} title="Classifier" /> : <ErrorPanel title="Classifier configuration couldn't be loaded" message={adapter.message} />}
      </div>
      {runs.ok ? <RunTable page={runs.data} query={{}} base="/cv/movements/runs" kind="movement" controls={false} /> : null}
    </div>
  );
}
