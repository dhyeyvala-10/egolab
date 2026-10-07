"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { browserApi } from "@/lib/api/browser";
import type { DatasetFacets, DatasetPreview, DatasetSummary, MovementClassRead, Ref, VersionSummary } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { defaultSpec, fullCounts, GROUP_OPTIONS, SPLITS, STATUS_OPTIONS, type Spec } from "@/lib/datasets";
import { SplitBar } from "./SplitBar";

type Filters = Spec["filters"];
type DatasetSpec = Spec;

function toggle<T>(list: T[], v: T): T[] {
  return list.includes(v) ? list.filter((x) => x !== v) : [...list, v];
}

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <fieldset className="flex min-w-0 flex-col gap-2 border-t border-line pt-3 first:border-t-0 first:pt-0">
      <legend className="float-left mb-1 w-full text-[13px] font-semibold">{title}{hint ? <span className="ml-2 text-xs font-normal text-ink-3">{hint}</span> : null}</legend>
      {children}
    </fieldset>
  );
}

function Chips({ options, value, onChange, label }: { options: { value: string; label: string; count?: number }[]; value: string[]; onChange: (v: string[]) => void; label: string }) {
  if (!options.length) return <p className="text-xs text-ink-3">None yet.</p>;
  return (
    <div className="flex flex-wrap gap-1.5" role="group" aria-label={label}>
      {options.map((o) => {
        const on = value.includes(o.value);
        return (
          <button key={o.value} type="button" aria-pressed={on} onClick={() => onChange(toggle(value, o.value))}
                  className={cn("h-7 rounded-md border px-2 text-xs", on ? "border-ink bg-ink text-canvas" : "border-line-strong hover:bg-hover")}>
            {o.label}{o.count != null ? <span className={cn("ml-1 tabular-nums", on ? "text-canvas/70" : "text-ink-3")}>{o.count}</span> : null}
          </button>
        );
      })}
    </div>
  );
}

/**
 * Build a dataset version: filters over videos (session, device, environment, quality) and samples (class,
 * review status, confidence, hand, object), a train/val/test split that keeps groups together, and a live
 * preview of what the version would contain. Creating it pins its inputs; a worker builds it.
 */
export function DatasetBuilder({ datasets, sessions, devices, classes, facets, initialDataset }: {
  datasets: DatasetSummary[];
  sessions: Ref[];
  devices: Ref[];
  classes: MovementClassRead[];
  facets: DatasetFacets;
  initialDataset?: string;
}) {
  const router = useRouter();
  const [datasetId, setDatasetId] = useState(initialDataset ?? datasets[0]?.id ?? "");
  const [newName, setNewName] = useState("");
  const [spec, setSpec] = useState<DatasetSpec>(defaultSpec);
  const [note, setNote] = useState("");
  const [preview, setPreview] = useState<DatasetPreview | null>(null);
  const [previewed, setPreviewed] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [sessionQuery, setSessionQuery] = useState("");
  const seq = useRef(0);

  const f = spec.filters;
  const setF = (patch: Partial<Filters>) => setSpec((s) => ({ ...s, filters: { ...s.filters, ...patch } }));
  const setSplit = (patch: Partial<DatasetSpec["split"]>) => setSpec((s) => ({ ...s, split: { ...s.split, ...patch } }));
  const ratioOk = Math.abs(spec.split.train + spec.split.val + spec.split.test - 1) < 1e-6;

  const specKey = JSON.stringify(spec);
  const previewing = specKey !== previewed;
  useEffect(() => {
    if (!ratioOk || !f.statuses.length) return;
    const n = ++seq.current;
    const t = setTimeout(() => {
      void browserApi<DatasetPreview>("/datasets/preview", { method: "POST", body: spec }).then((res) => {
        if (n !== seq.current) return;
        setPreviewed(specKey);
        if (res.ok) {
          setPreview(res.data);
          setError(null);
        } else setError(res.message);
      });
    }, 350);
    return () => clearTimeout(t);
  }, [spec, specKey, ratioOk, f.statuses.length]);

  const shownSessions = useMemo(() => sessions.filter((s) => s.name.toLowerCase().includes(sessionQuery.toLowerCase())).slice(0, 200), [sessions, sessionQuery]);
  const dataset = datasets.find((d) => d.id === datasetId);

  const create = async () => {
    setBusy(true);
    setError(null);
    let id = datasetId;
    if (id === "__new") {
      const made = await browserApi<{ id: string }>("/datasets", { method: "POST", body: { name: newName.trim() } });
      if (!made.ok) {
        setBusy(false);
        return setError(made.message);
      }
      id = made.data.id;
    }
    const res = await browserApi<VersionSummary>(`/datasets/${id}/versions`, { method: "POST", body: { spec, note: note.trim() || null } });
    setBusy(false);
    if (!res.ok) return setError(res.message);
    router.push(`/datasets/versions/${res.data.id}`);
  };

  const input = "h-[30px] rounded-md border border-line-strong bg-canvas px-2 text-xs";
  const pct = (v: number) => Math.round(v * 1000) / 10;
  const setRatio = (k: "train" | "val" | "test", v: string) => {
    const n = Math.max(0, Math.min(100, Number(v) || 0)) / 100;
    setSplit({ [k]: Math.round(n * 1000) / 1000 } as Partial<DatasetSpec["split"]>);
  };

  return (
    <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
      <div className="flex min-w-0 flex-col gap-4 rounded-lg border border-line bg-canvas p-4" data-testid="builder">
        <Section title="Dataset">
          <div className="flex flex-wrap items-center gap-2">
            <select aria-label="Dataset" value={datasetId} onChange={(e) => setDatasetId(e.target.value)} className={`${input} max-w-72`}>
              {datasets.map((d) => <option key={d.id} value={d.id}>{d.name}{d.latest_version ? ` (v${d.latest_version})` : ""}</option>)}
              <option value="__new">New dataset…</option>
            </select>
            {datasetId === "__new" ? <input aria-label="New dataset name" value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="Name" className={`${input} w-56`} /> : null}
            <span className="text-xs text-ink-3">{dataset ? `The next version is v${(dataset.latest_version ?? 0) + 1}.` : "Versions are numbered from v1."}</span>
          </div>
        </Section>

        <Section title="Videos" hint="Pinned when the version is created">
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center justify-between gap-2 text-xs">
              <span className="font-medium text-ink-2">Sessions {f.session_ids.length ? `(${f.session_ids.length} chosen)` : "(all)"}</span>
              <input aria-label="Find sessions" value={sessionQuery} onChange={(e) => setSessionQuery(e.target.value)} placeholder="Find" className={`${input} w-40`} />
            </div>
            <Chips label="Sessions" options={shownSessions.map((s) => ({ value: s.id, label: s.name }))} value={f.session_ids} onChange={(v) => setF({ session_ids: v })} />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5"><span className="text-xs font-medium text-ink-2">Devices</span>
              <Chips label="Devices" options={devices.map((d) => ({ value: d.id, label: d.name }))} value={f.device_ids} onChange={(v) => setF({ device_ids: v })} /></div>
            <div className="flex flex-col gap-1.5"><span className="text-xs font-medium text-ink-2">Environments</span>
              <Chips label="Environments" options={facets.environments.map((e) => ({ value: e, label: e }))} value={f.environments} onChange={(v) => setF({ environments: v })} /></div>
          </div>
          <div className="flex flex-col gap-1.5"><span className="text-xs font-medium text-ink-2">Leave out videos flagged</span>
            <div className="flex flex-col gap-1">
              {facets.quality_flags.map((q) => (
                <label key={q.flag} className="flex items-center gap-2 text-xs">
                  <input type="checkbox" checked={f.exclude_quality_flags.includes(q.flag)} onChange={() => setF({ exclude_quality_flags: toggle(f.exclude_quality_flags, q.flag) })} />
                  <span className="font-medium">{q.flag.replace(/_/g, " ")}</span><span className="text-ink-3">{q.description} · {q.videos} video{q.videos === 1 ? "" : "s"}</span>
                </label>
              ))}
            </div>
          </div>
        </Section>

        <Section title="Samples" hint="As the data stands when the version is created">
          <div className="flex flex-col gap-1.5"><span className="text-xs font-medium text-ink-2">Movement classes {f.classes.length ? "" : "(all)"}</span>
            <Chips label="Classes" options={classes.map((c) => ({ value: c.name, label: c.label, count: c.events }))} value={f.classes} onChange={(v) => setF({ classes: v })} /></div>
          <div className="flex flex-col gap-1.5"><span className="text-xs font-medium text-ink-2">Review status</span>
            <Chips label="Review status" options={STATUS_OPTIONS.map((s) => ({ value: s.value, label: s.label }))} value={f.statuses}
                   onChange={(v) => setF({ statuses: v as Filters["statuses"] })} />
            <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={f.human_verified_only} onChange={(e) => setF({ human_verified_only: e.target.checked })} /> Confirmed by a person only (leave out auto-accepted)</label>
            {!f.statuses.length ? <p className="text-xs text-error">Choose at least one status.</p> : null}
          </div>
          <div className="flex flex-wrap items-end gap-3 text-xs">
            <label className="flex flex-col gap-1"><span className="font-medium text-ink-2">Min confidence</span>
              <input aria-label="Min confidence" className={`${input} w-20`} inputMode="decimal" value={f.min_confidence ?? ""} onChange={(e) => setF({ min_confidence: e.target.value === "" ? null : Math.max(0, Math.min(1, Number(e.target.value))) })} /></label>
            <label className="flex flex-col gap-1"><span className="font-medium text-ink-2">Max confidence</span>
              <input aria-label="Max confidence" className={`${input} w-20`} inputMode="decimal" value={f.max_confidence ?? ""} onChange={(e) => setF({ max_confidence: e.target.value === "" ? null : Math.max(0, Math.min(1, Number(e.target.value))) })} /></label>
            <span className="pb-1.5 text-ink-3">Model confidence; corrections have none and always pass.</span>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5"><span className="text-xs font-medium text-ink-2">Hand</span>
              <Chips label="Hand" options={[{ value: "left", label: "Left" }, { value: "right", label: "Right" }]} value={f.handedness} onChange={(v) => setF({ handedness: v as Filters["handedness"] })} /></div>
            <div className="flex flex-col gap-1.5"><span className="text-xs font-medium text-ink-2">Object</span>
              <select aria-label="Object required" className={`${input} w-48`} value={f.require_object == null ? "" : f.require_object ? "yes" : "no"}
                      onChange={(e) => setF({ require_object: e.target.value === "" ? null : e.target.value === "yes" })}>
                <option value="">With or without</option><option value="yes">With an object</option><option value="no">Without an object</option>
              </select></div>
          </div>
          {facets.object_labels.length ? (
            <div className="flex flex-col gap-1.5"><span className="text-xs font-medium text-ink-2">Objects {f.object_labels.length ? "" : "(any)"}</span>
              <Chips label="Objects" options={facets.object_labels.map((o) => ({ value: o, label: o }))} value={f.object_labels} onChange={(v) => setF({ object_labels: v })} /></div>
          ) : null}
        </Section>

        <Section title="Split" hint="Deterministic: the same seed gives the same split">
          <div className="flex flex-wrap items-end gap-3 text-xs">
            {SPLITS.map((k) => (
              <label key={k} className="flex flex-col gap-1"><span className="font-medium capitalize text-ink-2">{k} %</span>
                <input aria-label={`${k} percent`} className={`${input} w-20`} inputMode="numeric" value={pct(spec.split[k])} onChange={(e) => setRatio(k, e.target.value)} /></label>
            ))}
            <label className="flex flex-col gap-1"><span className="font-medium text-ink-2">Keep together</span>
              <select aria-label="Group by" className={`${input} w-40`} value={spec.split.group_by} onChange={(e) => setSplit({ group_by: e.target.value as DatasetSpec["split"]["group_by"] })}>
                {GROUP_OPTIONS.map((g) => <option key={g.value} value={g.value}>{g.label}</option>)}
              </select></label>
            <label className="flex flex-col gap-1"><span className="font-medium text-ink-2">Seed</span>
              <input aria-label="Seed" className={`${input} w-20`} inputMode="numeric" value={spec.split.seed} onChange={(e) => setSplit({ seed: Math.max(0, Math.floor(Number(e.target.value) || 0)) })} /></label>
          </div>
          <p className="text-xs text-ink-3">{GROUP_OPTIONS.find((g) => g.value === spec.split.group_by)?.hint}. {!ratioOk ? <span className="text-error">Train + val + test must add up to 100%.</span> : null}</p>
        </Section>

        <Section title="Note" hint="Optional: what this version is for">
          <textarea aria-label="Note" value={note} onChange={(e) => setNote(e.target.value)} className="min-h-[56px] rounded-md border border-line-strong p-2 text-xs" />
        </Section>
      </div>

      <aside className="flex min-w-0 flex-col gap-3 rounded-lg border border-line bg-canvas p-4 xl:sticky xl:top-4" aria-label="Preview" data-testid="preview">
        <div className="flex items-baseline justify-between">
          <h2 className="text-[13px] font-semibold">Preview</h2>
          <span className="text-xs text-ink-3" aria-live="polite">{previewing ? "Updating…" : preview ? `${preview.videos} videos · ${preview.runs} runs` : ""}</span>
        </div>
        {preview ? (
          <>
            <div className="flex items-baseline gap-2"><span className="text-[26px] font-semibold tabular-nums leading-none" data-testid="preview-count">{preview.sample_count}{preview.truncated ? "+" : ""}</span><span className="text-xs text-ink-2">samples</span></div>
            <SplitBar counts={preview.counts} />
            {preview.warnings.map((w) => <p key={w} className="rounded-md border border-warning-line bg-warning-bg px-2 py-1.5 text-xs text-warning">{w}</p>)}
            <div className="max-h-72 overflow-auto rounded-md border border-line">
              <table className="w-full text-xs" data-testid="preview-classes">
                <thead className="sticky top-0 bg-subtle text-left text-ink-3"><tr><th className="px-2 py-1 font-semibold">Class</th>{SPLITS.map((s) => <th key={s} className="px-2 py-1 text-right font-semibold capitalize">{s}</th>)}</tr></thead>
                <tbody>
                  {Object.entries(fullCounts(preview.counts).classes).map(([c, n]) => (
                    <tr key={c} className="border-t border-line"><td className="px-2 py-1">{classes.find((k) => k.name === c)?.label ?? c}</td>{SPLITS.map((s) => <td key={s} className="px-2 py-1 text-right tabular-nums">{n[s]}</td>)}</tr>
                  ))}
                  {!Object.keys(fullCounts(preview.counts).classes).length ? <tr><td colSpan={4} className="px-2 py-4 text-center text-ink-3">No samples match.</td></tr> : null}
                </tbody>
              </table>
            </div>
            <p className="text-xs text-ink-3">Status: {Object.entries(fullCounts(preview.counts).statuses).map(([k, n]) => `${k.replace(/_/g, " ")} ${n}`).join(" · ") || "—"}{fullCounts(preview.counts).sources.auto_corrected ? ` · ${fullCounts(preview.counts).sources.auto_corrected} corrections` : ""}</p>
          </>
        ) : <p className="text-xs text-ink-3">{error ?? "Working out what matches…"}</p>}
        {error && preview ? <p className="text-xs text-error" role="alert">{error}</p> : null}
        <button type="button" onClick={() => void create()} disabled={busy || !ratioOk || !f.statuses.length || !preview?.sample_count || (datasetId === "__new" && !newName.trim())}
                className="h-[34px] rounded-md bg-ink px-4 text-xs font-semibold text-canvas disabled:opacity-50">
          Create version
        </button>
        <p className="text-xs text-ink-3">It records these filters, pins the matching videos, their classification runs, and this moment, so it can be rebuilt exactly. Versions never change once built.</p>
      </aside>
    </div>
  );
}
