import type { Metadata } from "next";
import { AdminOnly } from "@/components/settings/AdminOnly";
import { UserTable } from "@/components/settings/UserTable";
import { PageHeader } from "@/components/ui";
import { ErrorPanel } from "@/components/ui/ErrorPanel";
import { api } from "@/lib/api/client";
import { requireAdmin } from "@/lib/auth/admin";
import { ROLE_CHOICES } from "@/lib/roles";

export const metadata: Metadata = { title: "Users" };

export default async function UsersPage() {
  const { session, allowed } = await requireAdmin("/settings/users");
  if (!session) return null;
  const header = (
    <PageHeader
      eyebrow="Settings"
      title="Users"
      description="Everyone who signs in with Google starts with no access. Give each person only what they need. Admins are set in OWNER_EMAIL on the server and can't be changed here."
    />
  );
  if (!allowed) return <div className="flex max-w-[1100px] flex-col gap-5">{header}<AdminOnly /></div>;
  const users = await api.users(session.token);
  const waiting = users.ok ? users.data.items.filter((u) => u.role === "pending" && u.is_active).length : 0;
  return (
    <div className="flex max-w-[1100px] flex-col gap-5">
      {header}
      {waiting ? (
        <div className="rounded-lg border border-warning-line bg-warning-bg px-4 py-3 text-sm text-warning">
          {waiting === 1 ? "1 person is" : `${waiting} people are`} waiting for access.
        </div>
      ) : null}
      {users.ok ? <UserTable users={users.data.items} me={session.user.id} /> : <ErrorPanel title="People couldn't be loaded" message={users.message} />}
      <dl className="grid gap-x-6 gap-y-1 text-xs text-ink-2 sm:grid-cols-2">
        {ROLE_CHOICES.map((r) => (
          <div key={r.value} className="flex gap-1.5">
            <dt className="font-semibold text-ink">{r.label}:</dt>
            <dd>{r.help}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
