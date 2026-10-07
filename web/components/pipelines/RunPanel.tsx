"use client";

import { useState } from "react";
import { browserApi } from "@/lib/api/browser";
import type { RunSummary } from "@/lib/api/types";

export interface Option {
  id: string;
  name: string;
  hint?: string;
}

export interface InputsValue {
  session_ids: string[];
  dataset_ids: string[];
  all_videos: boolean;
}

export const emptyInputs = (): InputsValue => ({ session_ids: [], dataset_ids: [], all_videos: false });

/** Choose what a run (or a schedule) processes: sessions, datasets, or every video. */
export function InputsPicker({ value, onChange, sessions, datasets }: {
  value: InputsValue;
  onChange: (v: InputsValue) => void;
  sessions: Option[];
  datasets: Option[];
}) {
  const toggle = (key: "session_ids" | "dataset_ids", id: string) =>
    onChange({ ...value, [key]: value[key].includes(id) ? value[key].filter((x) => x !== id) : [...value[key], id] });
  const list = (title: string, key: "session_ids" | "dataset_ids", options: Option[]) => (
    <fieldset className="flex min-w-0 flex-1 flex-col gap-1" disabled={value.all_videos}>
      <legend className="font-medium">{title}</legend>
      {options.length ? (
        <div className="flex max-h-40 flex-col gap-0.5 overflow-auto rounded-md border border-line p-1.5">
          {options.map((o) => (
            <label key={o.id} className="flex items-center gap-2">
              <input type="checkbox" checked={value[key].includes(o.id)} onChange={() => toggle(key, o.id)} />
              <span className="truncate">{o.name}</span>
              {o.hint ? <span className="ml-auto shrink-0 text-ink-3">{o.hint}</span> : null}
            </label>
          ))}
        </div>
      ) : <span className="text-ink-3">None yet.</span>}
    </fieldset>
  );
  return (
    <div className="flex flex-col gap-2 text-xs">
      <div className="flex flex-col gap-3 md:flex-row">
        {list("Sessions", "session_ids", sessions)}
        {list("Datasets (their sessions)", "dataset_ids", datasets)}
      </div>
      <label className="flex items-center gap-2">
        <input type="checkbox" checked={value.all_videos} onChange={(e) => onChange({ ...value, all_videos: e.target.checked })} />
        All ingested videos
      </label>
    </div>
  );
}

export function selectedSomething(v: InputsValue) {
  return v.all_videos || v.session_ids.length > 0 || v.dataset_ids.length > 0;
}

/** Start a run of the pipeline's latest version on the chosen videos. */
export function RunPanel({ pipelineId, sessions, datasets, onClose, onStarted }: {
  pipelineId: string;
  sessions: Option[];
  datasets: Option[];
  onClose: () => void;
  onStarted: (run: RunSummary) => void;
}) {
  const [value, setValue] = useState<InputsValue>(emptyInputs);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const start = async () => {
    setBusy(true);
    setError(null);
    const inputs = value.all_videos ? { all_videos: true } : { session_ids: value.session_ids, dataset_ids: value.dataset_ids };
    const res = await browserApi<RunSummary>(`/pipelines/${pipelineId}/runs`, { method: "POST", body: { inputs } });
    setBusy(false);
    if (res.ok) onStarted(res.data);
    else setError(res.message);
  };
  return (
    <section aria-label="Run the pipeline" className="flex flex-col gap-3 rounded-lg border border-accent bg-canvas p-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">Run on…</h2>
        <button type="button" onClick={onClose} className="text-xs text-ink-3 hover:underline">Close</button>
      </div>
      <InputsPicker value={value} onChange={setValue} sessions={sessions} datasets={datasets} />
      <p className="text-[11px] text-ink-3">The videos are pinned when the run starts. Videos still being ingested are left out.</p>
      {error ? <p role="alert" className="text-xs text-error">{error}</p> : null}
      <div>
        <button type="button" disabled={busy || !selectedSomething(value)} onClick={start}
                className="inline-flex h-[30px] items-center rounded-md bg-accent px-3 text-xs font-semibold text-on-accent hover:opacity-90 disabled:opacity-50">
          {busy ? "Starting…" : "Start run"}
        </button>
      </div>
    </section>
  );
}
