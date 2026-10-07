"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { browserApi } from "@/lib/api/browser";
import type { GraphCheck, PipelineDetail, PipelineSummary, RunSummary, StepTypeRead } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import {
  asGraph,
  autoLayout,
  byCategory,
  completeLayout,
  uniqueId,
  type GraphNode,
  type Layout,
  type PipelineGraph,
} from "@/lib/pipelines";
import { Canvas, edgeKey, type NodeInfo } from "./Canvas";
import { ConfigForm } from "./ConfigForm";
import { RunPanel, type Option } from "./RunPanel";

const btn = "inline-flex h-[30px] items-center rounded-md border border-line-strong px-3 text-xs font-medium hover:bg-hover disabled:opacity-50";
const primary = "inline-flex h-[30px] items-center rounded-md bg-ink px-3 text-xs font-semibold text-canvas hover:opacity-90 disabled:opacity-50";

interface BuilderProps {
  steps: StepTypeRead[];
  pipelines: PipelineSummary[];
  pipeline: PipelineDetail | null;
  sessions: Option[];
  datasets: Option[];
  canEdit: boolean;
}

/** A save's outcome, for the pipeline it belongs to (a new pipeline's is shown once the page has it). */
interface SaveMessage {
  pipelineId: string | null;
  tone: "ok" | "error";
  text: string;
}

/**
 * Build a pipeline: add steps from the palette, connect them (drag from a step's ● onto the next, or tick
 * "Runs after" in the step's panel), set each step's options, and save. Saving a changed graph makes the
 * next version; moving steps only saves the layout. The graph is checked by the API as you edit.
 *
 * The editor starts over from the saved pipeline after each save (its key changes), so the save's outcome
 * is kept here, outside it.
 */
export function PipelineBuilder(props: BuilderProps) {
  const { pipeline } = props;
  const [message, setMessage] = useState<SaveMessage | null>(null);
  return (
    <Editor
      key={pipeline ? `${pipeline.id}-${pipeline.latest_version}-${pipeline.updated_at}` : "new"}
      {...props}
      message={message && message.pipelineId === (pipeline?.id ?? null) ? message : null}
      setMessage={setMessage}
    />
  );
}

function Editor({ steps, pipelines, pipeline, sessions, datasets, canEdit, message, setMessage }: BuilderProps & {
  message: SaveMessage | null;
  setMessage: (m: SaveMessage | null) => void;
}) {
  const router = useRouter();
  const order = useMemo(() => steps.map((s) => s.key), [steps]);
  const catalog = useMemo(() => new Map(steps.map((s) => [s.key, s])), [steps]);
  const info = useMemo(
    () => Object.fromEntries(steps.map((s) => [s.key, { label: s.label, category: s.category, perVideo: s.per_video }])) as Record<string, NodeInfo>,
    [steps],
  );
  const initial = useMemo(() => asGraph(pipeline?.version.graph), [pipeline]);
  const [name, setName] = useState(pipeline?.name ?? "");
  const [description, setDescription] = useState(pipeline?.description ?? "");
  const [isTemplate, setIsTemplate] = useState(pipeline?.is_template ?? false);
  const [onUpload, setOnUpload] = useState(pipeline?.run_on_upload ?? false);
  const [graph, setGraph] = useState<PipelineGraph>(initial);
  const [layout, setLayout] = useState<Layout>(() => completeLayout(initial, (pipeline?.layout ?? {}) as Layout, order));
  const [selected, setSelected] = useState<string | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<string | null>(null);
  const [check, setCheck] = useState<GraphCheck | null>(null);
  const [saving, setSaving] = useState(false);
  const [note, setNote] = useState("");
  const [running, setRunning] = useState(false);

  const saved = useMemo(() => JSON.stringify(initial), [initial]);
  const dirtyGraph = JSON.stringify(graph) !== saved;
  const dirty = dirtyGraph || name !== (pipeline?.name ?? "") || description !== (pipeline?.description ?? "") ||
    isTemplate !== (pipeline?.is_template ?? false) || onUpload !== (pipeline?.run_on_upload ?? false) ||
    JSON.stringify(layout) !== JSON.stringify(completeLayout(initial, (pipeline?.layout ?? {}) as Layout, order));

  // Ask the API whether the graph is valid (debounced).
  useEffect(() => {
    if (!graph.nodes.length) return;
    const ctl = new AbortController();
    const t = setTimeout(async () => {
      try {
        const res = await browserApi<GraphCheck>("/pipelines/validate", { method: "POST", body: graph, signal: ctl.signal });
        if (res.ok) setCheck(res.data);
      } catch {
        /* aborted by a newer edit */
      }
    }, 350);
    return () => {
      clearTimeout(t);
      ctl.abort();
    };
  }, [graph]);
  const liveCheck = graph.nodes.length ? check : null;
  const errors = useMemo(() => {
    const out: Record<string, string[]> = {};
    for (const e of liveCheck?.errors ?? []) if (e.node_id) out[e.node_id] = [...(out[e.node_id] ?? []), e.message];
    return out;
  }, [liveCheck]);

  const used = new Set(graph.nodes.map((n) => n.type));
  const node = graph.nodes.find((n) => n.id === selected) ?? null;
  const step = node ? catalog.get(node.type) : undefined;

  const update = useCallback((id: string, patch: Partial<GraphNode>) => {
    setGraph((g) => ({ ...g, nodes: g.nodes.map((n) => (n.id === id ? { ...n, ...patch } : n)) }));
  }, []);
  const add = (s: StepTypeRead) => {
    const id = uniqueId(s.key, new Set(graph.nodes.map((n) => n.id)));
    const anchor = selected ? layout[selected] : null;
    const ys = Object.values(layout).map((p) => p.y);
    const at = anchor ? { x: anchor.x + 230, y: anchor.y } : { x: 24, y: ys.length ? Math.max(...ys) + 96 : 24 };
    setGraph((g) => ({
      nodes: [...g.nodes, { id, type: s.key, config: { ...s.defaults }, retries: 0 }],
      edges: selected && anchor ? [...g.edges, { from: selected, to: id }] : g.edges,
    }));
    setLayout((l) => ({ ...l, [id]: at }));
    setSelected(id);
  };
  const remove = (id: string) => {
    setGraph((g) => ({ nodes: g.nodes.filter((n) => n.id !== id), edges: g.edges.filter((e) => e.from !== id && e.to !== id) }));
    setLayout((l) => Object.fromEntries(Object.entries(l).filter(([k]) => k !== id)));
    setSelected(null);
  };
  const connect = (from: string, to: string) => {
    if (from === to) return;
    setGraph((g) => (g.edges.some((e) => e.from === from && e.to === to) ? g : { ...g, edges: [...g.edges, { from, to }] }));
  };
  const disconnect = (key: string) => {
    setGraph((g) => ({ ...g, edges: g.edges.filter((e) => edgeKey(e.from, e.to) !== key) }));
    setSelectedEdge(null);
  };
  const rename = (from: string, to: string) => {
    if (!to || to === from || graph.nodes.some((n) => n.id === to)) return;
    setGraph((g) => ({
      nodes: g.nodes.map((n) => (n.id === from ? { ...n, id: to } : n)),
      edges: g.edges.map((e) => ({ from: e.from === from ? to : e.from, to: e.to === from ? to : e.to })),
    }));
    setLayout((l) => {
      const { [from]: p, ...rest } = l;
      return { ...rest, [to]: p };
    });
    setSelected(to);
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (!canEdit || (e.target as HTMLElement).closest("input, textarea, select")) return;
    if (e.key === "Delete" || e.key === "Backspace") {
      if (selectedEdge) disconnect(selectedEdge);
      else if (selected) remove(selected);
    }
  };

  const save = async () => {
    setSaving(true);
    setMessage(null);
    const body = { name: name.trim(), description: description.trim() || null, is_template: isTemplate, run_on_upload: onUpload, graph, layout, note: note.trim() || null };
    const res = pipeline
      ? await browserApi<PipelineDetail>(`/pipelines/${pipeline.id}`, { method: "PUT", body })
      : await browserApi<PipelineDetail>("/pipelines", { method: "POST", body });
    setSaving(false);
    if (!res.ok) {
      const errs = res.kind === "http" ? (res.detail as { errors?: { message: string }[] } | null)?.errors : undefined;
      setMessage({ pipelineId: pipeline?.id ?? null, tone: "error", text: errs?.length ? errs.map((e) => e.message).join(" · ") : res.message });
      return;
    }
    const before = pipeline?.latest_version ?? 0;
    setMessage({ pipelineId: res.data.id, tone: "ok",
                 text: res.data.latest_version > before ? `Saved as version ${res.data.latest_version}` : `Saved (steps unchanged, still version ${res.data.latest_version})` });
    setNote("");
    if (!pipeline) router.replace(`/pipelines/builder?id=${res.data.id}`);
    else router.refresh();
  };

  return (
    <div className="flex flex-col gap-3" onKeyDown={onKey}>
      <div className="flex flex-wrap items-end gap-2 rounded-lg border border-line bg-canvas p-3">
        <div className="flex min-w-[200px] flex-col gap-1 text-xs">
          <label htmlFor="pipeline-pick" className="font-medium text-ink-2">Pipeline</label>
          <select
            id="pipeline-pick"
            className="h-[30px] rounded-md border border-line-strong bg-canvas px-2"
            value={pipeline?.id ?? ""}
            onChange={(e) => router.push(e.target.value ? `/pipelines/builder?id=${e.target.value}` : "/pipelines/builder")}
          >
            <option value="">New pipeline…</option>
            {pipelines.map((p) => <option key={p.id} value={p.id}>{p.name}{p.is_template ? " (template)" : ""}{p.run_on_upload ? " (runs on uploads)" : ""} · v{p.latest_version}</option>)}
          </select>
        </div>
        <div className="flex min-w-[200px] flex-1 flex-col gap-1 text-xs">
          <label htmlFor="pipeline-name" className="font-medium text-ink-2">Name</label>
          <input id="pipeline-name" value={name} onChange={(e) => setName(e.target.value)} disabled={!canEdit} placeholder="e.g. Nightly processing"
                 className="h-[30px] rounded-md border border-line-strong bg-canvas px-2" />
        </div>
        <div className="flex min-w-[200px] flex-[2] flex-col gap-1 text-xs">
          <label htmlFor="pipeline-desc" className="font-medium text-ink-2">Description</label>
          <input id="pipeline-desc" value={description} onChange={(e) => setDescription(e.target.value)} disabled={!canEdit}
                 className="h-[30px] rounded-md border border-line-strong bg-canvas px-2" />
        </div>
        <label className="flex h-[30px] items-center gap-1.5 text-xs" title="Listed on the Templates page, for new pipelines to start from">
          <input type="checkbox" checked={isTemplate} disabled={!canEdit} onChange={(e) => setIsTemplate(e.target.checked)} />
          Save as a template
        </label>
        <label className="flex h-[30px] items-center gap-1.5 text-xs" title="Starts on every newly uploaded video as soon as its upload checks finish">
          <input type="checkbox" checked={onUpload} disabled={!canEdit} onChange={(e) => setOnUpload(e.target.checked)} />
          Run automatically on new uploads
        </label>
        {pipeline ? <span className="self-center rounded-md bg-hover px-2 py-1 font-mono text-[11px]" data-testid="version">v{pipeline.latest_version}</span> : null}
        <button type="button" className={btn} onClick={() => setLayout(autoLayout(graph, order))}>Tidy layout</button>
        {canEdit ? (
          <button type="button" className={primary} disabled={saving || !name.trim() || !graph.nodes.length || !dirty} onClick={save}>
            {saving ? "Saving…" : pipeline ? "Save" : "Create pipeline"}
          </button>
        ) : null}
        {pipeline && canEdit ? (
          <button type="button" className={btn} disabled={dirty} title={dirty ? "Save your changes first" : undefined} onClick={() => setRunning((r) => !r)}>
            Run…
          </button>
        ) : null}
      </div>
      {dirtyGraph && pipeline ? (
        <div className="flex flex-wrap items-center gap-2 text-xs text-ink-2">
          <span>Unsaved changes to the steps: saving makes version {pipeline.latest_version + 1}.</span>
          <label htmlFor="version-note" className="sr-only">What changed</label>
          <input id="version-note" value={note} onChange={(e) => setNote(e.target.value)} placeholder="What changed (optional)"
                 className="h-[26px] min-w-[240px] rounded-md border border-line-strong bg-canvas px-2" />
        </div>
      ) : null}
      {message ? (
        <p role="status" className={cn("rounded-md border px-3 py-1.5 text-xs", message.tone === "ok" ? "border-success-line bg-success-bg text-success" : "border-error-line bg-error-bg text-error")}>
          {message.text}
        </p>
      ) : null}
      {running && pipeline ? (
        <RunPanel pipelineId={pipeline.id} sessions={sessions} datasets={datasets} onClose={() => setRunning(false)}
                  onStarted={(r: RunSummary) => router.push(`/pipelines/runs/${r.id}`)} />
      ) : null}

      <div className="grid items-start gap-3 xl:grid-cols-[220px_minmax(0,1fr)_320px]">
        <aside aria-label="Steps" className="flex flex-col gap-3 rounded-lg border border-line bg-canvas p-3 text-xs">
          <p className="text-ink-3">{canEdit ? "Add a step. With a step selected, the new one runs after it." : "Steps a pipeline can use."}</p>
          {byCategory(steps).map(([cat, list]) => (
            <div key={cat} className="flex flex-col gap-1">
              <div className="text-[10px] font-semibold uppercase tracking-wider text-ink-3">{cat}</div>
              {list.map((s) => (
                <button key={s.key} type="button" disabled={!canEdit || used.has(s.key)} onClick={() => add(s)} title={s.description}
                        className="flex items-center justify-between rounded-md border border-line px-2 py-1.5 text-left hover:bg-hover disabled:cursor-not-allowed disabled:opacity-45">
                  <span className="font-medium">{s.label}</span>
                  <span className="text-ink-3">{used.has(s.key) ? "added" : "+"}</span>
                </button>
              ))}
            </div>
          ))}
        </aside>

        <div className="flex min-w-0 flex-col gap-2">
          {graph.nodes.length ? (
            <Canvas graph={graph} layout={layout} info={info} selected={selected} selectedEdge={selectedEdge} errors={errors}
                    onSelect={setSelected} onSelectEdge={setSelectedEdge} editable={canEdit}
                    onMove={(id, x, y) => setLayout((l) => ({ ...l, [id]: { x, y } }))} onConnect={connect}
                    className="min-h-[420px]" />
          ) : (
            <div className="flex min-h-[420px] flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-line-strong bg-subtle p-6 text-center text-xs text-ink-2">
              <span className="text-sm font-semibold text-ink">No steps yet</span>
              Add steps from the list, or start from a template on the Templates page.
            </div>
          )}
          <div className="flex flex-wrap items-center gap-2 text-xs" data-testid="graph-check">
            {liveCheck ? (
              liveCheck.ok ? <span className="text-success">✓ Valid: {graph.nodes.length} steps, {graph.edges.length} links</span> : (
                <ul className="flex flex-col gap-0.5 text-error">
                  {liveCheck.errors.map((e, i) => <li key={i}>✗ {e.node_id ? <b>{e.node_id}: </b> : null}{e.message}</li>)}
                </ul>
              )
            ) : null}
            {selectedEdge && canEdit ? (
              <button type="button" className={btn} onClick={() => disconnect(selectedEdge)}>Remove link {selectedEdge.replace(">", " → ")}</button>
            ) : null}
          </div>
        </div>

        <aside aria-label="Selected step" className="flex flex-col gap-3 rounded-lg border border-line bg-canvas p-3 text-xs">
          {node && step ? (
            <>
              <div>
                <div className="text-[10px] font-semibold uppercase tracking-wider text-ink-3">{step.category} · {step.per_video ? "per video" : "once per run"}</div>
                <h2 className="text-sm font-semibold">{step.label}</h2>
                <p className="mt-1 text-ink-2">{step.description}</p>
                {step.requires.length ? <p className="mt-1 text-ink-3">Needs {step.requires.map((r) => catalog.get(r)?.label ?? r).join(", ")} before it.</p> : null}
                {step.uses.length ? <p className="mt-1 text-ink-3">Reads {step.uses.map((r) => catalog.get(r)?.label ?? r).join(", ")} from a step before it, or else the video&apos;s latest run.</p> : null}
              </div>
              <div className="flex flex-col gap-1">
                <label htmlFor="node-id" className="font-medium">Step id</label>
                <input id="node-id" key={node.id} defaultValue={node.id} disabled={!canEdit} onBlur={(e) => rename(node.id, e.target.value.trim())}
                       className="h-[30px] rounded-md border border-line-strong bg-canvas px-2 font-mono" />
              </div>
              <fieldset className="flex flex-col gap-1" disabled={!canEdit}>
                <legend className="font-medium">Runs after</legend>
                {graph.nodes.filter((n) => n.id !== node.id).map((n) => {
                  const on = graph.edges.some((e) => e.from === n.id && e.to === node.id);
                  return (
                    <label key={n.id} className="flex items-center gap-2">
                      <input type="checkbox" checked={on} onChange={() => (on ? disconnect(edgeKey(n.id, node.id)) : connect(n.id, node.id))} />
                      {catalog.get(n.type)?.label ?? n.type} <span className="font-mono text-ink-3">{n.id}</span>
                    </label>
                  );
                })}
                {graph.nodes.length === 1 ? <span className="text-ink-3">Add another step to connect it.</span> : null}
              </fieldset>
              <div className="flex flex-col gap-1">
                <label htmlFor="node-retries" className="font-medium">Automatic retries</label>
                <input id="node-retries" type="number" min={0} max={5} value={node.retries} disabled={!canEdit}
                       onChange={(e) => update(node.id, { retries: Math.max(0, Math.min(5, Math.round(Number(e.target.value) || 0))) })}
                       className="h-[30px] w-24 rounded-md border border-line-strong bg-canvas px-2" />
                <span className="text-[11px] text-ink-3">After a transient failure (storage down, a worker lost), try again on its own, waiting longer each time.</span>
              </div>
              <fieldset disabled={!canEdit} className="flex flex-col gap-2 border-t border-line pt-3">
                <legend className="sr-only">Settings</legend>
                <ConfigForm schema={step.config_schema} value={node.config} onChange={(config) => update(node.id, { config })} />
              </fieldset>
              {errors[node.id] ? <ul className="text-error">{errors[node.id].map((m) => <li key={m}>✗ {m}</li>)}</ul> : null}
              {canEdit ? <button type="button" className={cn(btn, "text-error")} onClick={() => remove(node.id)}>Remove step</button> : null}
            </>
          ) : (
            <p className="text-ink-3">Select a step to see what it does and change its settings. Drag steps to arrange them; press Delete to remove the selected step or link.</p>
          )}
        </aside>
      </div>
    </div>
  );
}
