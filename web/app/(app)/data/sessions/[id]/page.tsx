import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { DatasetMembership } from "@/components/data/DatasetMembership";
import { VideoTable } from "@/components/data/VideoTable";
import { PageHeader, StatCard, StatusBadge } from "@/components/ui";
import { ErrorPanel } from "@/components/ui/ErrorPanel";
import { KeyValues } from "@/components/ui/KeyValues";
import { Panel } from "@/components/ui/Panel";
import { api } from "@/lib/api/client";
import { requireSession } from "@/lib/auth/session";
import { formatBytes, formatDateTime, formatDuration } from "@/lib/format";
import { pickQuery } from "@/lib/query";

export const metadata: Metadata = { title: "Session" };

export default async function SessionPage({ params, searchParams }: PageProps<"/data/sessions/[id]">) {
  const { id } = await params;
  const session = await requireSession(`/data/sessions/${id}`);
  if (!session) return null;
  const query = pickQuery(await searchParams, ["q", "status", "source_kind", "sort", "order", "offset"]);
  const res = await api.session(session.token, id);
  if (!res.ok && res.kind === "http" && (res.status === 404 || res.status === 422)) notFound();
  if (!res.ok) return <ErrorPanel title="Session couldn't be loaded" message={res.message} />;
  const s = res.data;
  const [videos, datasets] = await Promise.all([
    api.videos(session.token, { ...query, session_id: id, limit: 50 }),
    api.datasets(session.token),
  ]);
  const problems = s.failed_uploads.length + s.corrupt_videos.length;
  const conditions = Object.entries(s.capture_conditions ?? {});

  return (
    <div className="flex max-w-[1760px] flex-col gap-5">
      <div className="text-xs text-ink-3">
        <Link href="/data/sessions" className="hover:text-ink">Sessions</Link> / {s.name}
      </div>
      <PageHeader
        title={s.name}
        description={[s.task, s.environment, s.location].filter(Boolean).join(" · ") || undefined}
        actions={
          <Link href={`/data/upload?session=${s.id}`} className="inline-flex h-[30px] items-center rounded-md bg-ink px-3 font-semibold text-canvas hover:opacity-90">
            Upload to this session
          </Link>
        }
      />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard label="Videos" value={s.stats.video_count} hint={s.active_uploads ? `${s.active_uploads} upload${s.active_uploads === 1 ? "" : "s"} in progress` : undefined} />
        <StatCard label="Footage" value={s.stats.total_duration_s !== null ? formatDuration(s.stats.total_duration_s) : null} />
        <StatCard label="Size" value={formatBytes(s.stats.total_size_bytes)} />
        <StatCard
          label="Needs attention"
          value={problems}
          hint={problems ? `${s.stats.corrupt_count} corrupt, ${s.failed_uploads.length} failed uploads` : "Nothing flagged"}
          href={s.stats.corrupt_count ? `/data/sessions/${s.id}?status=corrupt` : undefined}
        />
      </div>

      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
        <section className="flex min-w-0 flex-col gap-2">
          <h2 className="text-sm font-semibold">Videos</h2>
          {videos.ok ? (
            <VideoTable
              page={videos.data}
              query={query}
              showSession={false}
              emptyAction={
                <Link href={`/data/upload?session=${s.id}`} className="inline-flex h-[30px] items-center rounded-md border border-line-strong px-3 font-medium hover:bg-hover">
                  Upload videos
                </Link>
              }
            />
          ) : (
            <ErrorPanel title="Videos couldn't be loaded" message={videos.message} />
          )}
          {problems > 0 ? (
            <Panel title="Errors" hint="Failed uploads and unreadable files" className="mt-2">
              <ul className="divide-y divide-line">
                {s.corrupt_videos.map((v) => (
                  <li key={v.video_id} className="flex flex-col gap-0.5 py-2">
                    <div className="flex items-center gap-2">
                      <StatusBadge status="corrupt" />
                      <Link href={`/data/videos/${v.video_id}`} className="font-medium hover:underline">{v.filename}</Link>
                    </div>
                    <span className="font-mono text-[11px] text-ink-2">{v.error}</span>
                  </li>
                ))}
                {s.failed_uploads.map((u) => (
                  <li key={u.upload_id} className="flex flex-col gap-0.5 py-2">
                    <div className="flex items-center gap-2">
                      <StatusBadge status="failed" label="Upload failed" />
                      <span className="font-medium">{u.filename}</span>
                      <span className="text-xs text-ink-3">{formatDateTime(u.created_at)}</span>
                    </div>
                    <span className="font-mono text-[11px] text-ink-2">{u.error}</span>
                  </li>
                ))}
              </ul>
            </Panel>
          ) : null}
        </section>

        <div className="flex min-w-0 flex-col gap-4">
          <Panel title="Details">
            <KeyValues
              rows={[
                ["Operator", s.operator?.name],
                ["Device", s.device?.name],
                ["Started", s.started_at ? formatDateTime(s.started_at) : null],
                ["Ended", s.ended_at ? formatDateTime(s.ended_at) : null],
                ["Task", s.task],
                ["Environment", s.environment],
                ["Location", s.location],
                ...conditions.map(([k, v]): [string, React.ReactNode] => [k.replace(/_/g, " "), String(v)]),
                ["Notes", s.notes],
                ["Created", formatDateTime(s.created_at)],
              ]}
            />
          </Panel>
          <Panel title="Datasets">
            <DatasetMembership
              sessionId={s.id}
              member={s.datasets}
              all={datasets.ok ? datasets.data.items.map((d) => ({ id: d.id, name: d.name })) : []}
            />
          </Panel>
        </div>
      </div>
    </div>
  );
}
