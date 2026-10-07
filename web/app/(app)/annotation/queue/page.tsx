import type { Metadata } from "next";
import { AssignForm } from "@/components/annotation/AssignForm";
import { AssignmentTable } from "@/components/annotation/AssignmentTable";
import { PageHeader } from "@/components/ui";
import { ErrorPanel } from "@/components/ui/ErrorPanel";
import { Panel } from "@/components/ui/Panel";
import { api } from "@/lib/api/client";
import { requireSession } from "@/lib/auth/session";
import { pickQuery } from "@/lib/query";

export const metadata: Metadata = { title: "Annotation Queue" };

const KEYS = ["mine", "status", "offset"] as const;

export default async function QueuePage({ searchParams }: PageProps<"/annotation/queue">) {
  const session = await requireSession("/annotation/queue");
  if (!session) return null;
  const query = pickQuery(await searchParams, KEYS);
  const isLead = session.user.role === "admin" || session.user.role === "reviewer";
  const [assignments, sessions, videos, people] = await Promise.all([
    api.assignments(session.token, { ...query, limit: 50 }),
    isLead ? api.sessions(session.token, { limit: 200, sort: "created_at", order: "desc" }) : null,
    isLead ? api.videos(session.token, { status: "ready", limit: 200 }) : null,
    isLead ? api.assignableUsers(session.token) : null,
  ]);

  return (
    <div className="flex max-w-[1760px] flex-col gap-5">
      <PageHeader
        eyebrow="Annotation"
        title="Annotation Queue"
        description="Sessions and videos assigned to annotators. Progress counts videos with at least one human annotation."
      />
      {isLead ? (
        <Panel title="Assign work">
          {people?.ok && sessions?.ok && videos?.ok ? (
            <AssignForm
              people={people.data}
              sessions={sessions.data.items.map((s) => ({ id: s.id, name: s.name }))}
              videos={videos.data.items.map((v) => ({ id: v.id, name: v.original_filename }))}
            />
          ) : (
            <p className="text-xs text-error">Couldn&apos;t load sessions, videos, or people to assign.</p>
          )}
        </Panel>
      ) : null}
      {assignments.ok ? (
        <AssignmentTable page={assignments.data} query={query} userId={session.user.id} isLead={isLead} />
      ) : (
        <ErrorPanel title="Assignments couldn't be loaded" message={assignments.message} />
      )}
    </div>
  );
}
