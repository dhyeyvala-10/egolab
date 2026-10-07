import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { MoveVideoForm } from "@/components/data/MoveVideoForm";
import { AnnotatedVideos } from "@/components/pipelines/AnnotatedVideos";
import { EmptyState, PageHeader, StatusBadge } from "@/components/ui";
import { ErrorPanel } from "@/components/ui/ErrorPanel";
import { KeyValues } from "@/components/ui/KeyValues";
import { Panel } from "@/components/ui/Panel";
import { api } from "@/lib/api/client";
import { requireSession } from "@/lib/auth/session";
import { formatBytes, formatCount, formatDateTime, formatDuration, formatFps, formatResolution } from "@/lib/format";

export const metadata: Metadata = { title: "Video" };

const SOURCE: Record<string, string> = { file: "Uploaded file", archive_member: "File inside a ZIP", image_sequence: "Image sequence inside a ZIP" };

export default async function VideoPage({ params }: PageProps<"/data/videos/[id]">) {
  const { id } = await params;
  const session = await requireSession(`/data/videos/${id}`);
  if (!session) return null;
  const [res, sessions, annotated, quality, hands] = await Promise.all([
    api.video(session.token, id),
    api.sessions(session.token, { limit: 200 }),
    api.annotatedVideos(session.token, id),
    api.videoQuality(session.token, id),
    api.cvRuns(session.token, { video_id: id, kind: "hand_tracking", status: "succeeded", limit: 1 }),
  ]);
  if (!res.ok && res.kind === "http" && (res.status === 404 || res.status === 422)) notFound();
  if (!res.ok) return <ErrorPanel title="Video couldn't be loaded" message={res.message} />;
  const v = res.data;
  const mono = (s: string | null | undefined) => (s ? <span className="font-mono text-xs">{s}</span> : null);

  return (
    <div className="flex max-w-[1760px] flex-col gap-5">
      <div className="flex flex-col gap-1">
        <div className="text-xs text-ink-3">
          <Link href="/data/videos" className="hover:text-ink">Video Library</Link>
          {v.session ? (
            <>
              {" / "}
              <Link href={`/data/sessions/${v.session.id}`} className="font-mono hover:text-ink">{v.session.name}</Link>
            </>
          ) : null}
        </div>
        <PageHeader
          title={v.original_filename}
          description={<StatusBadge status={v.status} />}
          actions={
            v.proxy_url ? (
              <Link href={`/annotation/inspector/${v.id}`} className="inline-flex h-[30px] items-center rounded-md bg-ink px-3 font-semibold text-canvas hover:opacity-90">
                Open in inspector
              </Link>
            ) : undefined
          }
        />
      </div>

      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1.6fr)_minmax(320px,1fr)]">
        <div className="flex min-w-0 flex-col gap-4">
          <section className="overflow-hidden rounded-lg border border-line bg-ink">
            {v.proxy_url ? (
              <video src={v.proxy_url} controls preload="metadata" className="aspect-video w-full bg-ink" />
            ) : (
              <div className="bg-canvas">
                <EmptyState
                  title={v.status === "corrupt" ? "This file couldn't be read" : "Preparing playback"}
                  description={v.status === "corrupt" ? v.error : "The proxy is being generated. Refresh in a moment."}
                />
              </div>
            )}
          </section>
          {v.thumbnails_url ? (
            // eslint-disable-next-line @next/next/no-img-element -- presigned storage URL, not an optimisable asset
            <img src={v.thumbnails_url} alt={`Frames from ${v.original_filename}`} className="w-full rounded-md border border-line" />
          ) : null}
          {v.sidecars.length > 0 ? (
            <Panel title="Metadata sidecars" hint={`${v.sidecars.length} file${v.sidecars.length === 1 ? "" : "s"}`}>
              <div className="flex flex-col gap-3 py-1">
                {v.sidecars.map((s) => (
                  <div key={s.id} className="flex flex-col gap-1">
                    <div className="flex items-center gap-2 text-xs">
                      <span className="font-medium">{s.filename}</span>
                      <span className="text-ink-3">{s.format.toUpperCase()}</span>
                      {s.error ? <span className="text-error">{s.error}</span> : null}
                    </div>
                    {s.parsed !== null ? (
                      <pre className="max-h-48 overflow-auto rounded-md border border-line bg-subtle p-2 font-mono text-[11px]">
                        {JSON.stringify(s.parsed, null, 2).slice(0, 4000)}
                      </pre>
                    ) : null}
                  </div>
                ))}
              </div>
            </Panel>
          ) : null}
        </div>

        <div className="flex min-w-0 flex-col gap-4">
          <Panel title="Annotated video" hint="Skeletons, object boxes, and movements drawn on">
            <AnnotatedVideos videoId={v.id} items={annotated.ok ? annotated.data : []} canEdit={session.user.role !== "viewer"}
                             hasRuns={hands.ok && hands.data.total > 0} />
          </Panel>
          <Panel title="Quality" hint={quality.ok && quality.data.flags.length ? quality.data.flags.join(" · ") : "No flags"}>
            {quality.ok && quality.data.checks.length ? (
              <ul className="flex flex-col divide-y divide-line text-xs" data-testid="quality-checks">
                {quality.data.checks.map((c) => {
                  const m = c.metrics as Record<string, unknown>;
                  const summary = c.check === "duplicates"
                    ? `${(m.matches as unknown[] | undefined)?.length ?? 0} near-duplicate video(s)`
                    : c.check === "occlusion"
                      ? m.rate == null ? "no hands tracked" : `${Math.round(Number(m.rate) * 100)}% of finger observations occluded`
                      : `${Math.round(Number(m.fraction ?? 0) * 100)}% of ${String(m.samples)} sampled frames below ${String(m.threshold)}`;
                  return (
                    <li key={c.id} className="flex flex-wrap items-baseline gap-2 py-1.5">
                      <StatusBadge status={c.flagged ? "needs_review" : "ok"} label={c.flagged ? c.flag.replace(/_/g, " ") : "passed"} />
                      <span className="font-medium capitalize">{c.check.replace(/_/g, " ")}</span>
                      <span className="text-ink-2">{summary}</span>
                      <span className="ml-auto text-ink-3">{formatDateTime(c.created_at)}</span>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="py-1 text-xs text-ink-3">Not checked yet: add quality checks to a pipeline (blur, low light, occlusion, near-duplicates).</p>
            )}
          </Panel>
          <Panel title="Media" hint="Read from the file by ffprobe">
            <KeyValues
              rows={[
                ["Duration", v.duration_s !== null ? formatDuration(v.duration_s) : null],
                ["Resolution", v.width ? formatResolution(v.width, v.height) : null],
                ["Frame rate", v.fps !== null ? `${formatFps(v.fps)} fps` : v.source_kind === "image_sequence" ? "Not given at upload" : null],
                ["Frames", v.frame_count !== null ? formatCount(v.frame_count) : null],
                ["Codec", mono(v.codec)],
                ["Bit rate", v.bit_rate ? `${formatCount(Math.round(v.bit_rate / 1000))} kb/s` : null],
                ["Audio", v.has_audio === null ? null : v.has_audio ? "Yes" : "No"],
                ["File size", formatBytes(v.size_bytes)],
              ]}
            />
          </Panel>
          <Panel title="Camera metadata" hint="Tags found in the file">
            {v.camera_metadata && Object.keys(v.camera_metadata).length > 0 ? (
              <KeyValues rows={Object.entries(v.camera_metadata).map(([k, value]) => [k, String(value)])} />
            ) : (
              <p className="py-1 text-ink-3">The file carries no camera tags.</p>
            )}
          </Panel>
          <Panel title="Provenance">
            <KeyValues
              rows={[
                ["Source", SOURCE[v.source_kind] ?? v.source_kind],
                ["Path in archive", mono(v.source_path)],
                ["SHA-256", mono(v.sha256)],
                ["Raw object", mono(v.storage_key)],
                ["Upload", mono(v.upload_id)],
                ["Added", formatDateTime(v.created_at)],
                ...v.lineage.map((e): [string, React.ReactNode] => [
                  e.relation.replace(/_/g, " "),
                  <span key={e.parent_id} className="font-mono text-xs">{e.parent_type} {e.parent_id.slice(0, 8)}</span>,
                ]),
              ]}
            />
          </Panel>
          <Panel title="Session">
            <MoveVideoForm
              videoId={v.id}
              sessionId={v.session?.id ?? null}
              sessions={sessions.ok ? sessions.data.items.map((s) => ({ id: s.id, name: s.name })) : v.session ? [v.session] : []}
            />
          </Panel>
        </div>
      </div>
    </div>
  );
}
