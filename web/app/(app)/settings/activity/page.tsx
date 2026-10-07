import type { Metadata } from "next";
import Link from "next/link";
import { ActionTable, SignInTable } from "@/components/settings/ActivityTables";
import { AdminOnly } from "@/components/settings/AdminOnly";
import { PageHeader } from "@/components/ui";
import { ErrorPanel } from "@/components/ui/ErrorPanel";
import { api } from "@/lib/api/client";
import { requireAdmin } from "@/lib/auth/admin";
import { cn } from "@/lib/cn";
import { pickQuery } from "@/lib/query";

export const metadata: Metadata = { title: "Activity" };

export default async function ActivityPage({ searchParams }: PageProps<"/settings/activity">) {
  const { session, allowed } = await requireAdmin("/settings/activity");
  if (!session) return null;
  const header = (
    <PageHeader
      eyebrow="Settings"
      title="Activity"
      description="Every sign-in, with the browser and address it came from, and everything everyone did. Only you can see this."
    />
  );
  if (!allowed) return <div className="flex max-w-[1100px] flex-col gap-5">{header}<AdminOnly /></div>;
  const { user } = pickQuery(await searchParams, ["user"]);
  const filter = user ? { user_id: user } : {};
  const [users, signIns, actions] = await Promise.all([
    api.users(session.token),
    api.signIns(session.token, { limit: 50, ...filter }),
    api.activity(session.token, { limit: 100, ...filter }),
  ]);
  const people = users.ok ? users.data.items : [];
  const chip = (href: string, label: string, active: boolean) => (
    <Link key={href} href={href} aria-current={active ? "true" : undefined}
      className={cn("h-8 whitespace-nowrap rounded-full border px-3 leading-8", active ? "border-ink bg-ink text-ground" : "border-line hover:bg-hover")}>
      {label}
    </Link>
  );

  return (
    <div className="flex max-w-[1100px] flex-col gap-5">
      {header}
      <nav aria-label="Show activity of" className="flex flex-wrap gap-2 text-xs font-semibold">
        {chip("/settings/activity", "Everyone", !user)}
        {people.map((p) => chip(`/settings/activity?user=${p.id}`, p.name || p.email, user === p.id))}
      </nav>
      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold">Sign-ins</h2>
        {signIns.ok ? <SignInTable rows={signIns.data.items} /> : <ErrorPanel title="Sign-ins couldn't be loaded" message={signIns.message} />}
      </section>
      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold">What people did</h2>
        {actions.ok ? <ActionTable rows={actions.data.items} /> : <ErrorPanel title="Activity couldn't be loaded" message={actions.message} />}
      </section>
    </div>
  );
}
