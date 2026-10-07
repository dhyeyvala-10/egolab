"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { browserApi } from "@/lib/api/browser";
import type { PipelineDetail, StepTypeRead } from "@/lib/api/types";
import { asGraph, type Layout } from "@/lib/pipelines";
import { Canvas, type NodeInfo } from "./Canvas";

export interface TemplateCard {
  key: string;
  name: string;
  description: string;
  graph: unknown;
  layout: unknown;
  /** A saved template (a pipeline) rather than a built-in one. */
  pipelineId?: string;
}

/** Templates as cards with their graph; "Use" copies one into a new pipeline and opens it in the builder. */
export function TemplateCards({ templates, steps, canEdit, taken }: {
  templates: TemplateCard[];
  steps: StepTypeRead[];
  canEdit: boolean;
  taken: string[];
}) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const info = Object.fromEntries(steps.map((s) => [s.key, { label: s.label, category: s.category, perVideo: s.per_video }])) as Record<string, NodeInfo>;
  const label = new Map(steps.map((s) => [s.key, s.label]));

  const use = async (t: TemplateCard) => {
    setBusy(t.key);
    setError(null);
    let name = t.name;
    for (let i = 2; taken.includes(name); i++) name = `${t.name} ${i}`;
    const body = t.pipelineId ? { name, from_pipeline_id: t.pipelineId } : { name, from_template: t.key };
    const res = await browserApi<PipelineDetail>("/pipelines", { method: "POST", body });
    setBusy(null);
    if (!res.ok) return setError(res.message);
    router.push(`/pipelines/builder?id=${res.data.id}`);
  };

  return (
    <div className="flex flex-col gap-3">
      {error ? <p role="alert" className="text-xs text-error">{error}</p> : null}
      <ul className="grid gap-3 lg:grid-cols-2">
        {templates.map((t) => {
          const graph = asGraph(t.graph);
          return (
            <li key={t.key} className="flex min-w-0 flex-col gap-2 rounded-lg border border-line bg-canvas p-3" data-template={t.key}>
              <div className="flex items-start justify-between gap-2">
                <div>
                  <h2 className="text-sm font-semibold">{t.name}</h2>
                  <p className="text-xs text-ink-2">{t.description}</p>
                </div>
                {canEdit ? (
                  <button type="button" disabled={busy !== null} onClick={() => use(t)}
                          className="inline-flex h-[30px] shrink-0 items-center rounded-md bg-accent px-3 text-xs font-semibold text-on-accent hover:opacity-90 disabled:opacity-50">
                    {busy === t.key ? "Creating…" : "Use template"}
                  </button>
                ) : null}
              </div>
              <Canvas graph={graph} layout={t.layout as Layout} info={info} scale={0.55} className="max-h-[260px]" label={`${t.name} graph`} />
              <p className="text-[11px] text-ink-3">{graph.nodes.map((n) => label.get(n.type) ?? n.type).join(" · ")}</p>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
