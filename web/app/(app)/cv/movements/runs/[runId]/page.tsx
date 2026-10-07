import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { RunStatusRefresher } from "@/components/cv/RunStatusRefresher";
import { EventTable } from "@/components/movement/EventTable";
import { PageHeader, StatCard, StatusBadge } from "@/components/ui";
import { ErrorPanel } from "@/components/ui/ErrorPanel";
import { KeyValues } from "@/components/ui/KeyValues";
import { Panel } from "@/components/ui/Panel";
import { api } from "@/lib/api/client";
import { requireSession } from "@/lib/auth/session";
import { formatDateTime } from "@/lib/format";
import { pickQuery } from "@/lib/query";

export const metadata: Metadata = { title: "Movement classification run" };

const fmt = new Intl.NumberFormat("en-US");
const INPUT_PAGES: Record<string, string> = { hand_tracking: "/cv/hands", object_detection: "/cv/objects" };

export default async function MovementRunPage({ params, searchParams }: PageProps<"/cv/movements/runs/[runId]">) {
  const { runId } = await params;
  const session = await requireSession(`/cv/movements/runs/${runId}`);
  if (!session) return null;
  const query = pickQuery(await searchParams, ["class", "status", "handedness", "finger", "max_confidence", "sort", "offset"]);
  const res = await api.cvRun(session.token, runId);
  if (!res.ok && res.kind === "http" && (res.status === 404 || res.status === 422)) notFound();
  if (!res.ok) return <ErrorPanel title="Run couldn't be loaded" message={res.message} />;
  const run = res.data;
  if (run.kind !== "movement") notFound();
  const [events, classes] = await Promise.all([
    api.movementEvents(session.token, { ...query, run_id: run.id, limit: 50 }),
    api.movementClasses(session.token),
  ]);
  const done = run.status === "succeeded";
  const counts = Object.entries((run.stats.classes ?? {}) as Record<string, number>).sort((a, b) => b[1] - a[1]);
  const skipped = Object.entries((run.stats.skipped_inactive ?? {}) as Record<string, number>);

  return (
    <div className="flex max-w-[1760px] flex-col gap-5">
      <RunStatusRefresher status={run.status} />
      <div className="flex flex-col gap-1">
        <div className="text-xs text-ink-3">
          <Link href="/cv/movements" className="hover:text-ink">Movement Classification</Link> /{" "}
          <Link href={`/data/videos/${run.video.id}`} className="hover:text-ink">{run.video.name}</Link>
        </div>
        <PageHeader
          title={run.video.name}
          description={<StatusBadge status={run.status} />}
          actions={<Link href={`/annotation/inspector/${run.video.id}`} className="inline-flex h-[30px] items-center rounded-md bg-ink px-3 font-semibold text-canvas hover:opacity-90">Open in inspector</Link>}
        />
      </div>
      {run.status === "failed" ? <ErrorPanel title="This run failed" message={run.error ?? "Unknown error"} /> : null}
      {run.status === "waiting" ? <p className="text-xs text-ink-2">Waiting for the runs it reads to finish. It starts on its own.</p> : null}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard label="Events" value={done ? run.detections : null} hint={done ? `${counts.length} classes` : undefined} />
        <StatCard label="Needs review" value={done ? ((run.stats.needs_review as number) ?? 0) : null} hint={done ? `confidence below ${run.stats.review_confidence}` : undefined} />
        <StatCard label="Hand–object contacts" value={done ? ((run.stats.contact_segments as number) ?? 0) : null} hint="On the object-interaction track" />
        <StatCard label="Frames" value={run.frames_processed} hint={run.frames_total ? `of ${fmt.format(run.frames_total)}` : undefined} />
      </div>
      {events.ok && classes.ok && done ? <EventTable page={events.data} query={query} classes={classes.data} videos={[]} /> : null}
      <div className="grid items-start gap-4 lg:grid-cols-2">
        <Panel title="By class">
          {counts.length ? (
            <ul className="flex flex-col text-xs">
              {counts.map(([name, n]) => (
                <li key={name} className="flex justify-between border-t border-line py-1 first:border-t-0">
                  <Link href={`/cv/movements/runs/${run.id}?class=${name}`} className="hover:underline">{name.replace(/_/g, " ")}</Link>
                  <span className="tabular-nums">{n}</span>
                </li>
              ))}
            </ul>
          ) : <p className="py-2 text-xs text-ink-3">{done ? "No events." : "Available when the run succeeds."}</p>}
          {skipped.length ? <p className="mt-2 text-xs text-ink-3">Not recorded (class switched off): {skipped.map(([n, c]) => `${n} ×${c}`).join(", ")}</p> : null}
        </Panel>
        <Panel title="Provenance">
          <KeyValues
            rows={[
              ["Classifier", run.model_version ? <span key="m" className="font-mono text-xs">{run.model_version.name} {run.model_version.version}</span> : null],
              ["Config", <span key="c" className="font-mono text-xs break-all">{Object.keys(run.config).length ? JSON.stringify(run.config) : "defaults"}</span>],
              ...Object.entries(run.inputs).map(([kind, id]) => [
                `Reads (${kind.replace("_", " ")})`,
                <Link key={kind} href={`${INPUT_PAGES[kind] ?? "/cv/hands"}/${id}`} className="font-mono text-xs hover:underline">{id}</Link>,
              ] as [string, React.ReactNode]),
              ["Started", run.started_at ? formatDateTime(run.started_at) : null],
              ["Finished", run.finished_at ? formatDateTime(run.finished_at) : null],
            ]}
          />
        </Panel>
      </div>
    </div>
  );
}
