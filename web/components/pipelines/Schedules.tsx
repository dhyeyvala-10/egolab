"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { StatusBadge } from "@/components/ui";
import { browserApi } from "@/lib/api/browser";
import type { CronPreview, PipelineSummary, ScheduleRead } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { emptyInputs, InputsPicker, selectedSomething, type InputsValue, type Option } from "./RunPanel";

const PRESETS: [string, string][] = [
  ["Every 15 minutes", "*/15 * * * *"],
  ["Every hour", "0 * * * *"],
  ["Every night at 02:00", "0 2 * * *"],
  ["Weekdays at 06:30", "30 6 * * 1-5"],
  ["Sundays at 23:00", "0 23 * * 0"],
];
const ZONES = ["UTC", "Asia/Kolkata", "Europe/London", "Europe/Berlin", "America/New_York", "America/Los_Angeles", "Asia/Tokyo", "Australia/Sydney"];
const field = "h-[30px] rounded-md border border-line-strong bg-canvas px-2";

function when(iso: string, tz: string) {
  return new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeStyle: "short", timeZone: tz }).format(new Date(iso));
}

/** Cron schedules: each runs a pipeline's latest version on the videos it selects (only new ones, by default). */
export function Schedules({ schedules, pipelines, sessions, datasets, canEdit }: {
  schedules: ScheduleRead[];
  pipelines: PipelineSummary[];
  sessions: Option[];
  datasets: Option[];
  canEdit: boolean;
}) {
  const router = useRouter();
  const browserZone = typeof Intl !== "undefined" ? Intl.DateTimeFormat().resolvedOptions().timeZone : "UTC";
  const [pipelineId, setPipelineId] = useState(pipelines[0]?.id ?? "");
  const [name, setName] = useState("");
  const [cron, setCron] = useState("0 2 * * *");
  const [tz, setTz] = useState("UTC");
  const [onlyNew, setOnlyNew] = useState(true);
  const [inputs, setInputs] = useState<InputsValue>(emptyInputs);
  const [preview, setPreview] = useState<CronPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    const ctl = new AbortController();
    const t = setTimeout(async () => {
      try {
        const res = await browserApi<CronPreview>("/pipelines/schedules/preview", { method: "POST", body: { cron, timezone: tz }, signal: ctl.signal });
        if (res.ok) setPreview(res.data);
      } catch {
        /* superseded */
      }
    }, 250);
    return () => {
      clearTimeout(t);
      ctl.abort();
    };
  }, [cron, tz]);

  const create = async () => {
    setError(null);
    setBusy("create");
    const sel = inputs.all_videos ? { all_videos: true } : { session_ids: inputs.session_ids, dataset_ids: inputs.dataset_ids };
    const res = await browserApi<ScheduleRead>("/pipelines/schedules", {
      method: "POST",
      body: { pipeline_id: pipelineId, name: name.trim() || cron, cron, timezone: tz, inputs: sel, only_new: onlyNew },
    });
    setBusy(null);
    if (!res.ok) return setError(res.message);
    setName("");
    router.refresh();
  };
  const act = async (id: string, path: string, method: "POST" | "PATCH" | "DELETE", body?: unknown) => {
    setBusy(id);
    setError(null);
    const res = await browserApi<unknown>(path, { method, body });
    setBusy(null);
    if (!res.ok) setError(res.message);
    router.refresh();
  };

  return (
    <div className="flex flex-col gap-4">
      {error ? <p role="alert" className="rounded-md border border-error-line bg-error-bg px-3 py-1.5 text-xs text-error">{error}</p> : null}
      <div className="relative overflow-x-auto rounded-lg border border-line">
        <table className="w-full min-w-[900px] text-xs" data-testid="schedules">
          <thead className="bg-subtle text-left text-ink-3">
            <tr><th className="px-3 py-2 font-semibold">Schedule</th><th className="font-semibold">Pipeline</th><th className="font-semibold">When</th>
              <th className="font-semibold">Videos</th><th className="font-semibold">Next</th><th className="font-semibold">Last</th>
              <th className="pr-3 text-right font-semibold"><span className="sr-only">Actions</span></th></tr>
          </thead>
          <tbody>
            {schedules.map((s) => (
              <tr key={s.id} className="border-t border-line align-top hover:bg-hover" data-schedule={s.id}>
                <td className="px-3 py-2"><div className="font-semibold">{s.name}</div><StatusBadge status={s.enabled ? "succeeded" : "cancelled"} label={s.enabled ? "On" : "Off"} /></td>
                <td className="py-2"><Link href={`/pipelines/builder?id=${s.pipeline.id}`} className="hover:underline">{s.pipeline.name}</Link></td>
                <td className="py-2"><code className="rounded bg-hover px-1 font-mono">{s.cron}</code><div className="text-ink-3">{s.timezone}</div></td>
                <td className="py-2">{s.inputs_label}<div className="text-ink-3">{s.only_new ? "only new videos" : "every time: all of them"}</div></td>
                <td className="py-2">{s.enabled && s.upcoming.length ? <ul>{s.upcoming.map((u) => <li key={u}>{when(u, s.timezone)}</li>)}</ul> : <span className="text-ink-3">—</span>}</td>
                <td className="max-w-[240px] py-2">{s.last_run_at ? <div className="text-ink-3">{formatDateTime(s.last_run_at)}</div> : <span className="text-ink-3">Not yet</span>}
                  {s.last_outcome ? <div>{s.last_outcome}</div> : null}
                  {s.run_count ? <Link href={`/pipelines/runs?schedule_id=${s.id}`} className="underline">{s.run_count} run{s.run_count === 1 ? "" : "s"}</Link> : null}</td>
                <td className="py-2 pr-3 text-right">
                  {canEdit ? (
                    <span className="inline-flex flex-wrap justify-end gap-1.5">
                      <button type="button" disabled={busy === s.id} className="rounded-md border border-line-strong px-2 py-0.5 hover:bg-canvas" onClick={() => act(s.id, `/pipelines/schedules/${s.id}/run`, "POST")}>Run now</button>
                      <button type="button" disabled={busy === s.id} className="rounded-md border border-line-strong px-2 py-0.5 hover:bg-canvas" onClick={() => act(s.id, `/pipelines/schedules/${s.id}`, "PATCH", { enabled: !s.enabled })}>{s.enabled ? "Turn off" : "Turn on"}</button>
                      <button type="button" disabled={busy === s.id} className="rounded-md border border-line-strong px-2 py-0.5 text-error hover:bg-canvas" onClick={() => act(s.id, `/pipelines/schedules/${s.id}`, "DELETE")}>Delete</button>
                    </span>
                  ) : null}
                </td>
              </tr>
            ))}
            {!schedules.length ? <tr><td colSpan={7} className="px-3 py-6 text-center text-ink-3">No schedules yet.</td></tr> : null}
          </tbody>
        </table>
      </div>

      {canEdit ? (
        <section aria-label="New schedule" className="flex flex-col gap-3 rounded-lg border border-line bg-canvas p-3 text-xs">
          <h2 className="text-[13px] font-semibold">New schedule</h2>
          {!pipelines.length ? <p className="text-ink-3">Create a pipeline first.</p> : (
            <>
              <div className="flex flex-wrap items-end gap-3">
                <div className="flex flex-col gap-1"><label htmlFor="s-pipeline" className="font-medium">Pipeline</label>
                  <select id="s-pipeline" value={pipelineId} onChange={(e) => setPipelineId(e.target.value)} className={field}>
                    {pipelines.map((p) => <option key={p.id} value={p.id}>{p.name} · v{p.latest_version}</option>)}
                  </select></div>
                <div className="flex flex-col gap-1"><label htmlFor="s-name" className="font-medium">Name</label>
                  <input id="s-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Nightly" className={field} /></div>
                <div className="flex flex-col gap-1"><label htmlFor="s-cron" className="font-medium">Cron (minute hour day month weekday)</label>
                  <input id="s-cron" value={cron} onChange={(e) => setCron(e.target.value)} className={`${field} w-48 font-mono`} /></div>
                <div className="flex flex-col gap-1"><label htmlFor="s-tz" className="font-medium">Time zone</label>
                  <select id="s-tz" value={tz} onChange={(e) => setTz(e.target.value)} className={field}>
                    {[...new Set([browserZone, ...ZONES])].map((z) => <option key={z} value={z}>{z}</option>)}
                  </select></div>
              </div>
              <div className="flex flex-wrap gap-1.5" role="group" aria-label="Presets">
                {PRESETS.map(([label, expr]) => (
                  <button key={expr} type="button" aria-pressed={cron === expr} onClick={() => setCron(expr)}
                          className={`rounded-full border px-2 py-0.5 ${cron === expr ? "border-ink bg-ink text-canvas" : "border-line hover:bg-hover"}`}>{label}</button>
                ))}
              </div>
              <div data-testid="cron-preview" className="text-ink-2">
                {preview ? (preview.ok ? <>Next: {preview.upcoming.slice(0, 3).map((u) => when(u, tz)).join(" · ")}</> : <span className="text-error">{preview.error}</span>) : null}
              </div>
              <InputsPicker value={inputs} onChange={setInputs} sessions={sessions} datasets={datasets} />
              <label className="flex items-center gap-2"><input type="checkbox" checked={onlyNew} onChange={(e) => setOnlyNew(e.target.checked)} />
                Only videos this pipeline hasn&apos;t processed yet (in a run that succeeded)</label>
              <div>
                <button type="button" disabled={busy === "create" || !preview?.ok || !selectedSomething(inputs)} onClick={create}
                        className="inline-flex h-[30px] items-center rounded-md bg-ink px-3 font-semibold text-canvas hover:opacity-90 disabled:opacity-50">Create schedule</button>
              </div>
              <p className="text-[11px] text-ink-3">The scheduler checks every minute. Each firing runs the pipeline&apos;s latest version.</p>
            </>
          )}
        </section>
      ) : null}
    </div>
  );
}
