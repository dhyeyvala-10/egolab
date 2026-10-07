import type { Metadata } from "next";
import Link from "next/link";
import { VideoTable } from "@/components/data/VideoTable";
import { PageHeader, StatusBadge } from "@/components/ui";
import { ErrorPanel } from "@/components/ui/ErrorPanel";
import { Panel } from "@/components/ui/Panel";
import { api } from "@/lib/api/client";
import { requireSession } from "@/lib/auth/session";
import { pickQuery } from "@/lib/query";

export const metadata: Metadata = { title: "Video Inspector" };

const KEYS = ["q", "session_id", "sort", "order", "offset"] as const;

export default async function InspectorIndexPage({ searchParams }: PageProps<"/annotation/inspector">) {
  const session = await requireSession("/annotation/inspector");
  if (!session) return null;
  const query = pickQuery(await searchParams, KEYS);
  const [videos, sessions, mine] = await Promise.all([
    api.videos(session.token, { ...query, status: "ready", limit: 50 }),
    api.sessions(session.token, { limit: 200, sort: "created_at", order: "desc" }),
    api.assignments(session.token, { mine: true, status: "todo", limit: 20 }),
  ]);
  const inProgress = await api.assignments(session.token, { mine: true, status: "in_progress", limit: 20 });
  const queue = [...(inProgress.ok ? inProgress.data.items : []), ...(mine.ok ? mine.data.items : [])];

  return (
    <div className="flex max-w-[1760px] flex-col gap-5">
      <PageHeader
        eyebrow="Annotation"
        title="Video Inspector"
        description="Pick a video to step through frame by frame and annotate. Only videos with a playable proxy are listed."
      />
      {queue.length ? (
        <Panel title="Your queue" hint={`${queue.length} open`}>
          <ul className="flex flex-col divide-y divide-line">
            {queue.map((a) => (
              <li key={a.id} className="flex flex-wrap items-center gap-3 py-2">
                {a.video ? (
                  <Link href={`/annotation/inspector/${a.video.id}`} className="font-medium hover:underline">{a.video.name}</Link>
                ) : a.session ? (
                  <Link href={`/annotation/inspector?session_id=${a.session.id}`} className="font-mono text-xs font-medium hover:underline">{a.session.name}</Link>
                ) : null}
                <StatusBadge status={a.status} />
                <span className="text-xs text-ink-3">
                  {a.progress.annotated} of {a.progress.videos} video{a.progress.videos === 1 ? "" : "s"} annotated
                </span>
                {a.note ? <span className="truncate text-xs text-ink-2">{a.note}</span> : null}
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}
      {videos.ok ? (
        <VideoTable
          page={videos.data}
          query={query}
          linkBase="/annotation/inspector"
          showStatusFilter={false}
          sessions={sessions.ok ? sessions.data.items.map((s) => ({ id: s.id, name: s.name })) : undefined}
          emptyAction={
            <Link href="/data/upload" className="inline-flex h-[30px] items-center rounded-md border border-line-strong px-3 font-medium hover:bg-hover">
              Upload videos
            </Link>
          }
        />
      ) : (
        <ErrorPanel title="Videos couldn't be loaded" message={videos.message} />
      )}
    </div>
  );
}
