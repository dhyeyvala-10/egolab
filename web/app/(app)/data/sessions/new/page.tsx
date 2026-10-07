import type { Metadata } from "next";
import Link from "next/link";
import { NewSessionForm } from "@/components/data/NewSessionForm";
import { PageHeader } from "@/components/ui";
import { api } from "@/lib/api/client";
import { requireSession } from "@/lib/auth/session";

export const metadata: Metadata = { title: "New session" };

export default async function NewSessionPage() {
  const session = await requireSession("/data/sessions/new");
  if (!session) return null;
  const today = new Date().toISOString().slice(0, 10);
  const [next, operators, devices] = await Promise.all([
    api.nextSessionName(session.token, today),
    api.operators(session.token),
    api.devices(session.token, { limit: 200 }),
  ]);
  return (
    <div className="flex max-w-[1760px] flex-col gap-5">
      <div className="text-xs text-ink-3">
        <Link href="/data/sessions" className="hover:text-ink">Sessions</Link> / New
      </div>
      <PageHeader title="New session" description="Everything here is optional except the date the name is built from. You can upload videos into the session next." />
      <NewSessionForm
        nextName={next.ok ? next.data.name : `SESSION_${today.replace(/-/g, "_")}_NNN`}
        today={today}
        operators={operators.ok ? operators.data.items.map((o) => o.name) : []}
        devices={devices.ok ? devices.data.items.map((d) => d.name) : []}
      />
    </div>
  );
}
