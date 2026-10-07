import type { Metadata } from "next";
import Link from "next/link";
import { DailyChart } from "@/components/review/DailyChart";
import { PageHeader, StatCard } from "@/components/ui";
import { ErrorPanel } from "@/components/ui/ErrorPanel";
import { Panel } from "@/components/ui/Panel";
import { api } from "@/lib/api/client";
import { requireSession } from "@/lib/auth/session";
import { formatDateTime } from "@/lib/format";
import { pickQuery } from "@/lib/query";
import { pct } from "@/lib/review";

export const metadata: Metadata = { title: "Review metrics" };

const WINDOWS = [7, 30, 90] as const;

export default async function ReviewMetricsPage({ searchParams }: PageProps<"/annotation/review/metrics">) {
  const session = await requireSession("/annotation/review/metrics");
  if (!session) return null;
  const query = pickQuery(await searchParams, ["days", "session_id"]);
  const days = WINDOWS.includes(Number(query.days) as (typeof WINDOWS)[number]) ? Number(query.days) : 30;
  const res = await api.reviewMetrics(session.token, { days, session_id: query.session_id });
  if (!res.ok) return <ErrorPanel title="Metrics couldn't be loaded" message={res.message} />;
  const m = res.data;

  return (
    <div className="flex max-w-[1200px] flex-col gap-5">
      <div className="flex flex-col gap-1">
        <div className="text-xs text-ink-3"><Link href="/annotation/review" className="hover:text-ink">Review</Link> / Metrics</div>
        <PageHeader
          title="Review metrics"
          description="How often people correct the model, how accurate each class is against human review, and review throughput. Auto-accepted events never count as ground truth."
          actions={
            <div className="flex gap-1" role="group" aria-label="Window">
              {WINDOWS.map((d) => (
                <Link key={d} href={`/annotation/review/metrics?days=${d}`} aria-current={d === days ? "page" : undefined}
                      className={d === days ? "inline-flex h-[30px] items-center rounded-md bg-ink px-3 text-xs font-semibold text-canvas" : "inline-flex h-[30px] items-center rounded-md border border-line-strong px-3 text-xs font-medium hover:bg-hover"}>
                  {d} days
                </Link>
              ))}
            </div>
          }
        />
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <StatCard label="Predictions" value={m.predictions} hint={`${m.pending} waiting`} href="/annotation/review/work" />
        <StatCard label="Human reviewed" value={m.human_reviewed} hint={`${m.confirmed} accepted`} />
        <StatCard label="Correction rate" value={pct(m.correction_rate)} hint={`${m.corrected} corrected`} />
        <StatCard label="Rejection rate" value={pct(m.rejection_rate)} hint={`${m.rejected} rejected`} />
        <StatCard label="Auto-accepted" value={m.auto_accepted} hint="Excluded from accuracy" href="/annotation/review/rules" />
      </div>
      <Panel title="Accuracy per class" hint="Accepted ÷ human reviewed (accepted, corrected, or rejected by a person)">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[680px] text-xs" data-testid="class-metrics">
            <thead className="text-left text-ink-3">
              <tr><th className="py-1.5 font-semibold">Class</th><th className="w-[30%] font-semibold">Accuracy</th><th className="text-right font-semibold">Reviewed</th><th className="text-right font-semibold">Accepted</th><th className="text-right font-semibold">Corrected</th><th className="text-right font-semibold">Rejected</th><th className="text-right font-semibold">Auto</th><th className="text-right font-semibold">Waiting</th></tr>
            </thead>
            <tbody>
              {m.per_class.map((c) => (
                <tr key={c.movement_class.id} className="border-t border-line" data-class={c.movement_class.name}>
                  <td className="py-1.5"><Link href={`/annotation/review/work?class=${c.movement_class.name}`} className="font-medium hover:underline">{c.movement_class.label}</Link></td>
                  <td>
                    {c.accuracy == null ? <span className="text-ink-3">no human review yet</span> : (
                      <span className="flex items-center gap-2">
                        <span className="h-1.5 w-full max-w-40 overflow-hidden rounded-full bg-hover"><span className="block h-full rounded-full bg-ink" style={{ width: `${c.accuracy * 100}%` }} /></span>
                        <span className="w-12 tabular-nums">{pct(c.accuracy)}</span>
                      </span>
                    )}
                  </td>
                  <td className="text-right tabular-nums">{c.human_reviewed}</td>
                  <td className="text-right tabular-nums">{c.confirmed}</td>
                  <td className="text-right tabular-nums">{c.corrected}</td>
                  <td className="text-right tabular-nums">{c.rejected}</td>
                  <td className="text-right tabular-nums text-ink-2">{c.auto_accepted}</td>
                  <td className="text-right tabular-nums text-ink-2">{c.pending}</td>
                </tr>
              ))}
              {!m.per_class.length ? <tr><td colSpan={8} className="py-6 text-center text-ink-3">No predictions yet.</td></tr> : null}
            </tbody>
          </table>
        </div>
      </Panel>
      <div className="grid items-start gap-4 lg:grid-cols-2">
        <Panel title="Reviews per day" hint={`Last ${days} days`}>
          <DailyChart days={m.daily} />
        </Panel>
        <Panel title="Per annotator" hint="Per hour counts individual reviews and corrections, not bulk">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[480px] text-xs" data-testid="annotator-metrics">
              <thead className="text-left text-ink-3"><tr><th className="py-1.5 font-semibold">Person</th><th className="text-right font-semibold">Reviews</th><th className="text-right font-semibold">One by one</th><th className="text-right font-semibold">Bulk</th><th className="text-right font-semibold">Corrections</th><th className="text-right font-semibold">Per hour</th><th className="text-right font-semibold">Last</th></tr></thead>
              <tbody>
                {m.annotators.map((a) => (
                  <tr key={a.user.id} className="border-t border-line">
                    <td className="py-1.5 font-medium">{a.user.name}</td>
                    <td className="text-right tabular-nums">{a.reviews}</td>
                    <td className="text-right tabular-nums">{a.individual + a.inspector}</td>
                    <td className="text-right tabular-nums">{a.bulk}</td>
                    <td className="text-right tabular-nums">{a.corrections}</td>
                    <td className="text-right tabular-nums">{a.per_hour ?? "—"}</td>
                    <td className="text-right text-ink-2">{formatDateTime(a.last_at)}</td>
                  </tr>
                ))}
                {!m.annotators.length ? <tr><td colSpan={7} className="py-6 text-center text-ink-3">Nobody has reviewed in this window.</td></tr> : null}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>
    </div>
  );
}
