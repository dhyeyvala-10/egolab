import type { Metadata } from "next";
import Link from "next/link";
import { SessionTable } from "@/components/data/SessionTable";
import { PageHeader } from "@/components/ui";
import { ErrorPanel } from "@/components/ui/ErrorPanel";
import { api } from "@/lib/api/client";
import { requireSession } from "@/lib/auth/session";
import { pickQuery } from "@/lib/query";

export const metadata: Metadata = { title: "Sessions" };

export default async function SessionsPage({ searchParams }: PageProps<"/data/sessions">) {
  const session = await requireSession("/data/sessions");
  if (!session) return null;
  const query = pickQuery(await searchParams, ["q", "sort", "order", "offset"]);
  const res = await api.sessions(session.token, { ...query, limit: 50 });
  return (
    <div className="flex max-w-[1760px] flex-col gap-5">
      <PageHeader
        eyebrow="Data"
        title="Sessions"
        description="Capture sessions, named SESSION_YYYY_MM_DD_NNN, with who recorded them, on which device, and where."
        actions={
          <Link href="/data/sessions/new" className="inline-flex h-[30px] items-center rounded-md bg-ink px-3 font-semibold text-canvas hover:opacity-90">
            New session
          </Link>
        }
      />
      {res.ok ? <SessionTable page={res.data} query={query} /> : <ErrorPanel title="Sessions couldn't be loaded" message={res.message} />}
    </div>
  );
}
