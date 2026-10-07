import type { Metadata } from "next";
import { AdminOnly } from "@/components/settings/AdminOnly";
import { LimitsForm } from "@/components/settings/LimitsForm";
import { PageHeader } from "@/components/ui";
import { ErrorPanel } from "@/components/ui/ErrorPanel";
import { api } from "@/lib/api/client";
import { requireAdmin } from "@/lib/auth/admin";

export const metadata: Metadata = { title: "Limits" };

export default async function LimitsPage() {
  const { session, allowed } = await requireAdmin("/settings/limits");
  if (!session) return null;
  const header = <PageHeader eyebrow="Settings" title="Limits" description="What waits for your approval, and who may start processing." />;
  if (!allowed) return <div className="flex max-w-[1100px] flex-col gap-5">{header}<AdminOnly /></div>;
  const limits = await api.limits(session.token);
  return (
    <div className="flex max-w-[1100px] flex-col gap-5">
      {header}
      {limits.ok ? <LimitsForm limits={limits.data} /> : <ErrorPanel title="Limits couldn't be loaded" message={limits.message} />}
    </div>
  );
}
