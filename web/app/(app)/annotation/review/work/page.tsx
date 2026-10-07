import type { Metadata } from "next";
import Link from "next/link";
import { Workspace } from "@/components/review/Workspace";
import { PageHeader } from "@/components/ui";
import { ErrorPanel } from "@/components/ui/ErrorPanel";
import { api } from "@/lib/api/client";
import { requireSession } from "@/lib/auth/session";
import { pickQuery } from "@/lib/query";
import { canReview, isLead, queueQuery, scopeLabel, SORTS, WORKSPACE_KEYS, type WorkspaceQuery } from "@/lib/review";

export const metadata: Metadata = { title: "Review workspace" };

/** One class's (or object's, or everything's) review workspace, ordered by the active-learning queue. */
export default async function ReviewWorkPage({ searchParams }: PageProps<"/annotation/review/work">) {
  const session = await requireSession("/annotation/review/work");
  if (!session) return null;
  const query = pickQuery(await searchParams, WORKSPACE_KEYS) as WorkspaceQuery;
  const [queue, classes, sessions] = await Promise.all([
    api.reviewQueue(session.token, { ...queueQuery(query), limit: 50 }),
    api.movementClasses(session.token),
    api.sessions(session.token, { limit: 200, sort: "created_at", order: "desc" }),
  ]);
  const cls = classes.ok ? classes.data.find((c) => c.name === query.class) : undefined;
  const scope = scopeLabel(query, cls?.label);
  const keep = (k: keyof WorkspaceQuery) => (query[k] ? <input type="hidden" name={k} value={query[k]} /> : null);

  return (
    <div className="flex max-w-[1760px] flex-col gap-4">
      <div className="flex flex-col gap-1">
        <div className="text-xs text-ink-3"><Link href="/annotation/review" className="hover:text-ink">Review</Link> / {scope}</div>
        <PageHeader
          title={`Review · ${scope}`}
          description="Most useful first: the model's least confident calls, where model versions disagree, and the rarest classes. Reviewing never blocks processing."
        />
      </div>
      <form action="/annotation/review/work" className="flex flex-wrap items-end gap-2 text-xs" aria-label="View">
        {keep("class")}{keep("object")}{keep("no_object")}{keep("video_id")}
        <label className="flex flex-col gap-1">
          <span className="text-ink-2">Order</span>
          <select name="sort" defaultValue={query.sort ?? "priority"} className="h-[30px] rounded-md border border-line-strong bg-canvas px-2">
            {SORTS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-ink-2">Show</span>
          <select name="status" defaultValue={query.status ?? ""} className="h-[30px] rounded-md border border-line-strong bg-canvas px-2">
            <option value="">Everything pending</option>
            <option value="needs_review">Flagged only</option>
            <option value="auto_detected">Not flagged</option>
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-ink-2">Hand</span>
          <select name="handedness" defaultValue={query.handedness ?? ""} className="h-[30px] rounded-md border border-line-strong bg-canvas px-2">
            <option value="">Both</option>
            <option value="left">Left</option>
            <option value="right">Right</option>
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-ink-2">Session</span>
          <select name="session_id" defaultValue={query.session_id ?? ""} className="h-[30px] max-w-56 rounded-md border border-line-strong bg-canvas px-2">
            <option value="">All sessions</option>
            {sessions.ok ? sessions.data.items.map((s) => <option key={s.id} value={s.id}>{s.name}</option>) : null}
          </select>
        </label>
        <button type="submit" className="h-[30px] rounded-md border border-line-strong px-3 font-medium hover:bg-hover">Apply</button>
      </form>
      {queue.ok && classes.ok ? (
        canReview(session.user.role) ? (
          <Workspace key={JSON.stringify(query)} initial={queue.data} query={query} classes={classes.data} lead={isLead(session.user.role)} scope={scope} />
        ) : (
          <ErrorPanel title="Viewers can't review" message="Ask an admin for the annotator or reviewer role." />
        )
      ) : (
        <ErrorPanel title="The queue couldn't be loaded" message={!queue.ok ? queue.message : !classes.ok ? classes.message : ""} />
      )}
    </div>
  );
}
