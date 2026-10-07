import type { Metadata } from "next";
import Link from "next/link";
import { ProgressLegend, ReviewCards } from "@/components/review/ReviewCards";
import { EmptyState, PageHeader, StatCard } from "@/components/ui";
import { ErrorPanel } from "@/components/ui/ErrorPanel";
import { api } from "@/lib/api/client";
import type { ReviewGroup } from "@/lib/api/types";
import { requireSession } from "@/lib/auth/session";
import { cn } from "@/lib/cn";
import { pickQuery } from "@/lib/query";
import { isLead, pct } from "@/lib/review";

export const metadata: Metadata = { title: "Review" };

const KEYS = ["group", "session_id"] as const;

function workHref(g: ReviewGroup, group: string, sessionId?: string): string {
  const p = new URLSearchParams();
  if (group === "class") p.set("class", g.key);
  else if (g.key) p.set("object", g.key);
  else p.set("no_object", "1");
  if (sessionId) p.set("session_id", sessionId);
  return `/annotation/review/work?${p}`;
}

/**
 * Review home: one card per movement class (or per object), each opening its own workspace, so a reviewer
 * works through one kind of movement at a time instead of one long mixed list.
 */
export default async function ReviewPage({ searchParams }: PageProps<"/annotation/review">) {
  const session = await requireSession("/annotation/review");
  if (!session) return null;
  const query = pickQuery(await searchParams, KEYS);
  const group = query.group === "object" ? "object" : "class";
  const [summary, sessions, metrics, rules] = await Promise.all([
    api.reviewSummary(session.token, { group, session_id: query.session_id }),
    api.sessions(session.token, { limit: 200, sort: "created_at", order: "desc" }),
    api.reviewMetrics(session.token, { session_id: query.session_id }),
    api.reviewRules(session.token),
  ]);
  const lead = isLead(session.user.role);
  const activeRules = rules.ok ? rules.data.filter((r) => r.enabled).length : null;
  const tab = (value: string, label: string) => {
    const p = new URLSearchParams({ group: value, ...(query.session_id ? { session_id: query.session_id } : {}) });
    return (
      <Link href={`/annotation/review?${p}`} aria-current={group === value ? "page" : undefined}
            className={cn("inline-flex h-[30px] items-center rounded-md px-3 text-xs font-semibold", group === value ? "bg-ink text-canvas" : "border border-line-strong hover:bg-hover")}>
        {label}
      </Link>
    );
  };

  return (
    <div className="flex max-w-[1760px] flex-col gap-5">
      <PageHeader
        eyebrow="Annotation"
        title="Review"
        description="Accept, reject, or correct AI-detected movements. Nothing waits on review — it marks which labels a person has checked, so datasets can choose them."
        actions={
          <div className="flex flex-wrap gap-2">
            <Link href={`/annotation/review/work${query.session_id ? `?session_id=${query.session_id}` : ""}`} className="inline-flex h-[30px] items-center rounded-md bg-ink px-3 font-semibold text-canvas hover:opacity-90">
              Open the queue (all classes)
            </Link>
            <Link href="/annotation/review/rules" className="inline-flex h-[30px] items-center rounded-md border border-line-strong px-3 font-medium hover:bg-hover">Auto-accept rules</Link>
            <Link href="/annotation/review/metrics" className="inline-flex h-[30px] items-center rounded-md border border-line-strong px-3 font-medium hover:bg-hover">Metrics</Link>
          </div>
        }
      />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard label="To review" value={summary.ok ? summary.data.totals.pending : null} hint={summary.ok ? `${summary.data.totals.needs_review} flagged by the model or a person` : undefined} />
        <StatCard label="Human reviewed" value={metrics.ok ? metrics.data.human_reviewed : null} hint={metrics.ok ? `correction rate ${pct(metrics.data.correction_rate)}` : undefined} href="/annotation/review/metrics" />
        <StatCard label="Auto-accepted" value={metrics.ok ? metrics.data.auto_accepted : null} hint="By rules, not a person" href="/annotation/review/rules" />
        <StatCard label="Auto-accept rules" value={activeRules} hint={lead ? "Set per class" : "Set by leads"} href="/annotation/review/rules" />
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex gap-1.5" role="group" aria-label="Group by">{tab("class", "By movement")}{tab("object", "By object")}</div>
        <form className="flex items-center gap-2 text-xs" action="/annotation/review">
          <input type="hidden" name="group" value={group} />
          <label htmlFor="session_id" className="text-ink-2">Session</label>
          <select id="session_id" name="session_id" defaultValue={query.session_id ?? ""} className="h-[30px] max-w-56 rounded-md border border-line-strong bg-canvas px-2">
            <option value="">All sessions</option>
            {sessions.ok ? sessions.data.items.map((s) => <option key={s.id} value={s.id}>{s.name}</option>) : null}
          </select>
          <button type="submit" className="h-[30px] rounded-md border border-line-strong px-3 font-medium hover:bg-hover">Show</button>
        </form>
      </div>
      {!summary.ok ? (
        <ErrorPanel title="Review progress couldn't be loaded" message={summary.message} />
      ) : summary.data.groups.length === 0 ? (
        <EmptyState title="Nothing to review yet" description={<>Movement events appear here once videos are classified. <Link href="/annotation/auto" className="underline">Run auto annotation</Link>.</>} />
      ) : (
        <>
          <ReviewCards groups={summary.data.groups} hrefFor={(g) => workHref(g, group, query.session_id)} />
          <ProgressLegend />
        </>
      )}
    </div>
  );
}
