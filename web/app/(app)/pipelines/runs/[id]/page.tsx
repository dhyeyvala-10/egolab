import type { Metadata } from "next";
import Link from "next/link";
import { RunView } from "@/components/pipelines/RunView";
import { PageHeader } from "@/components/ui";
import { ErrorPanel } from "@/components/ui/ErrorPanel";
import { api } from "@/lib/api/client";
import { requireSession } from "@/lib/auth/session";

export const metadata: Metadata = { title: "Pipeline run" };

export default async function RunPage({ params }: PageProps<"/pipelines/runs/[id]">) {
  const { id } = await params;
  const session = await requireSession(`/pipelines/runs/${id}`);
  if (!session) return null;
  const [run, steps, catalog] = await Promise.all([
    api.pipelineRun(session.token, id),
    api.pipelineRunSteps(session.token, id, { limit: 500 }),
    api.pipelineSteps(session.token),
  ]);
  if (!run.ok) return <ErrorPanel title="Run couldn't be loaded" message={run.message} />;
  return (
    <div className="flex max-w-[1840px] flex-col gap-4">
      <PageHeader
        eyebrow="Pipelines · Run"
        title={`${run.data.pipeline.name} · run #${run.data.number}`}
        description="Every step for every video: status, attempts, duration, and why it failed. Retrying a failed step runs only that step (and then what was waiting on it); finished steps keep their results."
        actions={<Link href="/pipelines/runs" className="inline-flex h-[30px] items-center rounded-md border border-line-strong px-3 text-xs font-medium hover:bg-hover">All runs</Link>}
      />
      <RunView initial={run.data} initialSteps={steps.ok ? steps.data : { items: [], total: 0, limit: 500, offset: 0 }}
               steps={catalog.ok ? catalog.data : []} canEdit={session.user.role !== "viewer"} />
    </div>
  );
}
