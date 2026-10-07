import type { Metadata } from "next";
import Link from "next/link";
import { PipelineBuilder } from "@/components/pipelines/PipelineBuilder";
import { PageHeader } from "@/components/ui";
import { ErrorPanel } from "@/components/ui/ErrorPanel";
import { api } from "@/lib/api/client";
import { requireSession } from "@/lib/auth/session";
import { inputOptions } from "@/lib/pipelineInputs";
import { pickQuery } from "@/lib/query";

export const metadata: Metadata = { title: "Pipeline Builder" };

export default async function BuilderPage({ searchParams }: PageProps<"/pipelines/builder">) {
  const session = await requireSession("/pipelines/builder");
  if (!session) return null;
  const { id } = pickQuery(await searchParams, ["id"]);
  const [steps, pipelines, pipeline, options] = await Promise.all([
    api.pipelineSteps(session.token),
    api.pipelines(session.token, { limit: 200 }),
    id ? api.pipeline(session.token, id) : Promise.resolve(null),
    inputOptions(session.token),
  ]);
  if (!steps.ok) return <ErrorPanel title="The step catalogue couldn't be loaded" message={steps.message} />;
  if (pipeline && !pipeline.ok) return <ErrorPanel title="Pipeline couldn't be loaded" message={pipeline.message} />;
  const detail = pipeline?.ok ? pipeline.data : null;
  return (
    <div className="flex max-w-[1840px] flex-col gap-4">
      <PageHeader
        eyebrow="Pipelines"
        title={detail ? detail.name : "Pipeline Builder"}
        description="Chain processing steps into a graph: each runs per video (or once for the whole run) when the steps before it succeed. Saving a change makes a new version; runs record the version they ran."
        actions={
          <>
            <Link href="/pipelines/templates" className="inline-flex h-[30px] items-center rounded-md border border-line-strong px-3 text-xs font-medium hover:bg-hover">Start from a template</Link>
            {detail ? <Link href={`/pipelines/runs?pipeline_id=${detail.id}`} className="inline-flex h-[30px] items-center rounded-md border border-line-strong px-3 text-xs font-medium hover:bg-hover">Runs ({detail.run_count})</Link> : null}
          </>
        }
      />
      <PipelineBuilder
        steps={steps.data}
        pipelines={pipelines.ok ? pipelines.data.items : []}
        pipeline={detail}
        sessions={options.sessions}
        datasets={options.datasets}
        canEdit={session.user.role !== "viewer"}
      />
    </div>
  );
}
