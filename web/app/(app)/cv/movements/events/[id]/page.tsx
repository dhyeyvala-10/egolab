import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { EventView } from "@/components/movement/EventView";
import { EventReview } from "@/components/review/EventReview";
import { ConfidenceBadge, PageHeader, SourceBadge, StatusBadge } from "@/components/ui";
import { ErrorPanel } from "@/components/ui/ErrorPanel";
import { KeyValues } from "@/components/ui/KeyValues";
import { Panel } from "@/components/ui/Panel";
import { api } from "@/lib/api/client";
import { requireSession } from "@/lib/auth/session";
import { formatDateTime } from "@/lib/format";

export const metadata: Metadata = { title: "Movement event" };

export default async function MovementEventPage({ params }: PageProps<"/cv/movements/events/[id]">) {
  const { id } = await params;
  const session = await requireSession(`/cv/movements/events/${id}`);
  if (!session) return null;
  const res = await api.movementEvent(session.token, id);
  if (!res.ok && res.kind === "http" && (res.status === 404 || res.status === 422)) notFound();
  if (!res.ok) return <ErrorPanel title="Event couldn't be loaded" message={res.message} />;
  const event = res.data;
  const [video, history, classes] = await Promise.all([
    api.video(session.token, event.video.id),
    api.eventHistory(session.token, event.id),
    api.movementClasses(session.token),
  ]);
  const attrs = Object.entries(event.attributes ?? {}).filter(([, v]) => v !== null && v !== undefined);

  return (
    <div className="flex max-w-[1760px] flex-col gap-5">
      <div className="flex flex-col gap-1">
        <div className="text-xs text-ink-3">
          <Link href="/cv/movements" className="hover:text-ink">Movement Classification</Link> /{" "}
          <Link href={`/cv/movements?video_id=${event.video.id}`} className="hover:text-ink">{event.video.name}</Link>
        </div>
        <PageHeader
          title={event.label}
          description={
            <span className="flex flex-wrap items-center gap-2">
              <StatusBadge status={event.status} />
              {event.confidence != null ? <ConfidenceBadge value={event.confidence} modelVersion={`${event.model_version.name} ${event.model_version.version}`} /> : null}
              <SourceBadge source={event.source === "auto_corrected" ? "auto_corrected" : "auto"} />
              <span className="font-mono text-xs text-ink-3">f{event.start_frame}–f{event.end_frame}</span>
            </span>
          }
          actions={
            <Link href={`/annotation/inspector/${event.video.id}?frame=${event.start_frame}`} className="inline-flex h-[30px] items-center rounded-md bg-ink px-3 font-semibold text-canvas hover:opacity-90">
              Open in inspector
            </Link>
          }
        />
      </div>
      {event.superseded_at && history.ok ? (
        <p className="rounded-md border border-human-line bg-human-bg px-3 py-2 text-xs">
          This prediction was corrected. It is kept as the model made it;{" "}
          {(() => {
            const newer = history.data.versions.find((v) => v.source !== "auto" && !v.superseded_at);
            return newer ? <Link href={`/cv/movements/events/${newer.id}`} className="font-semibold underline">open the correction</Link> : "see the versions below";
          })()}.
        </p>
      ) : null}
      {event.parent_event_id ? (
        <p className="rounded-md border border-line bg-subtle px-3 py-2 text-xs">
          A person&apos;s correction of <Link href={`/cv/movements/events/${event.parent_event_id}`} className="font-semibold underline">the model&apos;s prediction</Link>. The evidence below is what the model saw.
        </p>
      ) : null}
      {session.user.role !== "viewer" && classes.ok ? <EventReview event={event} classes={classes.data} /> : null}
      {video.ok ? <EventView event={event} video={video.data} /> : <ErrorPanel title="Video couldn't be loaded" message={video.message} />}
      <div className="grid items-start gap-4 lg:grid-cols-2">
        <Panel title="Event record">
          <KeyValues
            rows={[
              ["Class", <span key="c"><span className="font-medium">{event.movement_class.label}</span> <span className="font-mono text-xs text-ink-3">{event.movement_class.name}</span></span>],
              ["Video", <Link key="v" href={`/data/videos/${event.video.id}`} className="hover:underline">{event.video.name}</Link>],
              ["Session", event.session ? <Link key="s" href={`/data/sessions/${event.session.id}`} className="hover:underline">{event.session.name}</Link> : null],
              ["Time", <span key="t" className="font-mono text-xs">{event.start_s.toFixed(3)}–{event.end_s.toFixed(3)} s</span>],
              ["Hand", `${event.handedness === "left" ? "Left" : "Right"}, track #${event.hand_track_id}`],
              ["Fingers", event.fingers.length ? event.fingers.join(", ") : "whole hand"],
              ["Object", event.object_label ? `${event.object_label}, track #${event.object_track_id}` : null],
              ...attrs.map(([k, v]) => [k.replace(/_/g, " "), <span key={k} className="font-mono text-xs">{String(v)}</span>] as [string, React.ReactNode]),
              ["Reviewed", event.reviewed_by ? `${event.reviewed_by.name}, ${event.reviewed_at ? formatDateTime(event.reviewed_at) : ""}` : null],
            ]}
          />
        </Panel>
        {history.ok ? (
          <Panel title="Versions and reviews" className="lg:col-span-2">
            <ol className="flex flex-col gap-1.5 text-xs" data-testid="versions">
              {history.data.versions.map((v, i) => (
                <li key={v.id} className="flex flex-wrap items-center gap-2">
                  <span className="w-6 tabular-nums text-ink-3">v{i + 1}</span>
                  <SourceBadge source={v.source === "auto_corrected" ? "auto_corrected" : "auto"} />
                  <Link href={`/cv/movements/events/${v.id}`} className={v.id === event.id ? "font-semibold" : "hover:underline"}>{v.movement_class.label}</Link>
                  <span className="font-mono text-ink-3">f{v.start_frame}–f{v.end_frame}</span>
                  <span className="text-ink-2">{v.object_label ?? "no object"}</span>
                  <StatusBadge status={v.status} />
                  {v.confidence != null ? <span className="font-mono text-ink-3">{v.confidence.toFixed(2)}</span> : null}
                </li>
              ))}
            </ol>
            {history.data.log.length ? (
              <table className="mt-3 w-full text-xs" data-testid="review-log">
                <thead className="text-left text-ink-3"><tr><th className="py-1 font-semibold">When</th><th className="font-semibold">Change</th><th className="font-semibold">How</th><th className="font-semibold">By</th></tr></thead>
                <tbody>
                  {history.data.log.map((r) => (
                    <tr key={r.id} className="border-t border-line">
                      <td className="py-1 tabular-nums">{formatDateTime(r.created_at)}</td>
                      <td>{r.from_status ? `${r.from_status.replace(/_/g, " ")} → ` : ""}{r.to_status.replace(/_/g, " ")}</td>
                      <td>{r.method.replace(/_/g, " ")}</td>
                      <td>{r.actor?.name ?? (r.method === "auto_rule" ? "auto-accept rule" : "—")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : <p className="mt-2 text-xs text-ink-3">Not reviewed yet.</p>}
          </Panel>
        ) : null}
        <Panel title="Provenance">
          <KeyValues
            rows={[
              ["Classifier", <span key="m" className="font-mono text-xs">{event.model_version.name} {event.model_version.version}</span>],
              ["Classification run", <Link key="r" href={`/cv/movements/runs/${event.run_id}`} className="font-mono text-xs hover:underline">{event.run_id}</Link>],
              ["Keypoints from", <Link key="h" href={`/cv/hands/${event.hand_run_id}`} className="font-mono text-xs hover:underline">{event.hand_run_id}</Link>],
              ["Objects from", event.object_run_id ? <Link key="o" href={`/cv/objects/${event.object_run_id}`} className="font-mono text-xs hover:underline">{event.object_run_id}</Link> : "no object run"],
              ["Timeline segment", <span key="a" className="font-mono text-xs">{event.annotation_id}</span>],
              ["Detected", formatDateTime(event.created_at)],
            ]}
          />
        </Panel>
      </div>
    </div>
  );
}
