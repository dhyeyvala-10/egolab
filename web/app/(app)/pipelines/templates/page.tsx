import type { Metadata } from "next";
import { TemplateCards } from "@/components/pipelines/TemplateCards";
import { PageHeader } from "@/components/ui";
import { ErrorPanel } from "@/components/ui/ErrorPanel";
import { api } from "@/lib/api/client";
import { requireSession } from "@/lib/auth/session";

export const metadata: Metadata = { title: "Templates" };

export default async function TemplatesPage() {
  const session = await requireSession("/pipelines/templates");
  if (!session) return null;
  const [templates, saved, steps, all] = await Promise.all([
    api.pipelineTemplates(session.token),
    api.pipelines(session.token, { templates: true, limit: 200 }),
    api.pipelineSteps(session.token),
    api.pipelines(session.token, { limit: 200 }),
  ]);
  if (!templates.ok || !steps.ok) return <ErrorPanel title="Templates couldn't be loaded" message={!templates.ok ? templates.message : steps.ok ? "" : steps.message} />;
  const savedDetails = saved.ok ? await Promise.all(saved.data.items.map((p) => api.pipeline(session.token, p.id))) : [];
  const cards = [
    ...templates.data.map((t) => ({ key: t.key, name: t.name, description: t.description, graph: t.graph, layout: t.layout })),
    ...savedDetails.flatMap((r) => (r.ok ? [{ key: r.data.id, name: r.data.name, description: r.data.description ?? "A saved template.",
      graph: r.data.version.graph, layout: r.data.layout, pipelineId: r.data.id }] : [])),
  ];
  return (
    <div className="flex max-w-[1760px] flex-col gap-5">
      <PageHeader
        eyebrow="Pipelines"
        title="Templates"
        description="Starting points: use one to make your own pipeline, then change any step in the builder. Save any pipeline as a template to reuse it."
      />
      <TemplateCards templates={cards} steps={steps.data} canEdit={session.user.role !== "viewer"}
                     taken={all.ok ? all.data.items.map((p) => p.name) : []} />
    </div>
  );
}
