import type { Metadata } from "next";
import Link from "next/link";
import { BatchHistory, RulesEditor } from "@/components/review/RulesEditor";
import { PageHeader } from "@/components/ui";
import { ErrorPanel } from "@/components/ui/ErrorPanel";
import { Panel } from "@/components/ui/Panel";
import { api } from "@/lib/api/client";
import { requireSession } from "@/lib/auth/session";
import { isLead } from "@/lib/review";

export const metadata: Metadata = { title: "Auto-accept rules" };

export default async function ReviewRulesPage() {
  const session = await requireSession("/annotation/review/rules");
  if (!session) return null;
  const [rules, classes, batches] = await Promise.all([
    api.reviewRules(session.token),
    api.movementClasses(session.token),
    api.reviewBatches(session.token, { limit: 50 }),
  ]);
  const lead = isLead(session.user.role);
  return (
    <div className="flex max-w-[1100px] flex-col gap-5">
      <div className="flex flex-col gap-1">
        <div className="text-xs text-ink-3"><Link href="/annotation/review" className="hover:text-ink">Review</Link> / Auto-accept rules</div>
        <PageHeader
          title="Auto-accept rules"
          description="Predictions at or above a confidence are accepted without a person, so reviewers only see the uncertain ones. They are recorded as auto-accepted, never as human review."
        />
      </div>
      <Panel title="Rules" hint={lead ? undefined : "Admins and reviewers set these"}>
        {rules.ok && classes.ok ? <RulesEditor rules={rules.data} classes={classes.data} lead={lead} /> : <ErrorPanel title="Rules couldn't be loaded" message={!rules.ok ? rules.message : !classes.ok ? classes.message : ""} />}
      </Panel>
      <Panel title="Bulk reviews" hint="Every bulk accept or reject, and every rule application">
        {batches.ok ? <BatchHistory batches={batches.data.items} lead={lead} /> : <ErrorPanel title="History couldn't be loaded" message={batches.message} />}
      </Panel>
    </div>
  );
}
