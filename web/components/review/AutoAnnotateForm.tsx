"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { browserApi } from "@/lib/api/browser";
import type { AutoAnnotateResult, CvRunKind, ModelVersionRead, SessionSummary } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";

const KINDS: { kind: CvRunKind; label: string }[] = [
  { kind: "hand_tracking", label: "Hand tracking" },
  { kind: "object_detection", label: "Object detection" },
  { kind: "movement", label: "Movement classification" },
];

type Choice = { mode: "configured" } | { mode: "version"; id: string } | { mode: "custom"; adapter: string; config: string };

/**
 * Run auto annotation on whole sessions with a chosen model version per kind: the configured setup, any
 * registered version (every adapter + config that has run), or a new configuration (a new version).
 */
export function AutoAnnotateForm({ sessions, versions }: { sessions: SessionSummary[]; versions: ModelVersionRead[] }) {
  const router = useRouter();
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [kinds, setKinds] = useState<Set<CvRunKind>>(new Set(["hand_tracking", "object_detection", "movement"]));
  const [choices, setChoices] = useState<Record<string, Choice>>({});
  const [stride, setStride] = useState("1");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AutoAnnotateResult | null>(null);
  const byKind = useMemo(() => {
    const m: Record<string, ModelVersionRead[]> = {};
    for (const v of versions) (m[v.kind] ??= []).push(v);
    return m;
  }, [versions]);
  const videos = sessions.filter((s) => picked.has(s.id)).reduce((n, s) => n + s.stats.ready_count, 0);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!picked.size) return setError("Choose at least one session.");
    if (!kinds.size) return setError("Choose what to run.");
    const models: Record<string, unknown> = {};
    for (const k of kinds) {
      const c = choices[k];
      if (!c || c.mode === "configured") continue;
      if (c.mode === "version") models[k] = { model_version_id: c.id };
      else {
        let config: unknown;
        try {
          config = c.config.trim() ? JSON.parse(c.config) : {};
        } catch {
          return setError(`${k.replace(/_/g, " ")}: the config isn't valid JSON.`);
        }
        if (!c.adapter.trim()) return setError(`${k.replace(/_/g, " ")}: name the adapter.`);
        models[k] = { adapter: c.adapter.trim(), config };
      }
    }
    setBusy(true);
    const res = await browserApi<AutoAnnotateResult>("/review/auto-annotate", {
      method: "POST",
      body: { session_ids: [...picked], kinds: KINDS.map((k) => k.kind).filter((k) => kinds.has(k)), models, stride: Math.max(1, Math.min(30, Number(stride) || 1)) },
    });
    setBusy(false);
    if (!res.ok) return setError(res.message);
    setResult(res.data);
    router.refresh();
  };

  const field = "h-[30px] rounded-md border border-line-strong bg-canvas px-2 text-xs";
  return (
    <form onSubmit={submit} className="flex flex-col gap-4 text-xs" aria-label="Auto annotation">
      <fieldset className="flex min-w-0 flex-col gap-2">
        <legend className="mb-1 text-[13px] font-semibold">1 · Sessions</legend>
        {sessions.length ? (
          <div className="max-h-64 overflow-auto rounded-md border border-line">
            <table className="w-full">
              <tbody>
                {sessions.map((s) => (
                  <tr key={s.id} className="border-t border-line first:border-t-0">
                    <td className="w-8 px-2 py-1.5"><input type="checkbox" aria-label={s.name} checked={picked.has(s.id)} onChange={(e) => setPicked((p) => { const n = new Set(p); if (e.target.checked) n.add(s.id); else n.delete(s.id); return n; })} /></td>
                    <td className="py-1.5 font-mono">{s.name}</td>
                    <td className="py-1.5 text-ink-2">{[s.task, s.environment].filter(Boolean).join(" · ")}</td>
                    <td className="px-2 py-1.5 text-right tabular-nums text-ink-2">{s.stats.ready_count} ready of {s.stats.video_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <p className="text-ink-3">No sessions yet. <Link href="/data/upload" className="underline">Upload videos</Link> into a session first.</p>}
        <span className="text-ink-3">{picked.size} session{picked.size === 1 ? "" : "s"} · {videos} ready video{videos === 1 ? "" : "s"}</span>
      </fieldset>

      <fieldset className="flex min-w-0 flex-col gap-2">
        <legend className="mb-1 text-[13px] font-semibold">2 · Models</legend>
        {KINDS.map(({ kind, label }) => {
          const c = choices[kind] ?? { mode: "configured" };
          const list = byKind[kind] ?? [];
          const value = c.mode === "version" ? c.id : c.mode;
          return (
            <div key={kind} className="flex min-w-0 flex-col gap-1.5 rounded-md border border-line px-3 py-2" data-kind={kind}>
              <div className="flex flex-wrap items-center gap-3">
                <label className="flex w-48 items-center gap-1.5 font-medium"><input type="checkbox" checked={kinds.has(kind)} onChange={(e) => setKinds((s) => { const n = new Set(s); if (e.target.checked) n.add(kind); else n.delete(kind); return n; })} /> {label}</label>
                <select aria-label={`${label} model`} className={`${field} w-full min-w-0 sm:w-auto sm:flex-1`} disabled={!kinds.has(kind)} value={value}
                        onChange={(e) => setChoices((x) => ({ ...x, [kind]: e.target.value === "configured" ? { mode: "configured" } : e.target.value === "custom" ? { mode: "custom", adapter: "", config: "{}" } : { mode: "version", id: e.target.value } }))}>
                  <option value="configured">Configured setup (settings)</option>
                  {list.map((v) => <option key={v.id} value={v.id}>{v.name} {v.version}{v.configured ? " · configured" : ""} · {v.runs} run{v.runs === 1 ? "" : "s"}</option>)}
                  <option value="custom">New configuration…</option>
                </select>
              </div>
              {c.mode === "custom" ? (
                <div className="grid gap-2 sm:grid-cols-[200px_1fr]">
                  <input className={field} placeholder="adapter, e.g. rules" value={c.adapter} aria-label={`${label} adapter`} onChange={(e) => setChoices((x) => ({ ...x, [kind]: { ...c, adapter: e.target.value } }))} />
                  <textarea className="min-h-[60px] rounded-md border border-line-strong p-2 font-mono text-[11px]" value={c.config} aria-label={`${label} config`} onChange={(e) => setChoices((x) => ({ ...x, [kind]: { ...c, config: e.target.value } }))} />
                </div>
              ) : c.mode === "version" ? (
                <pre className="overflow-x-auto rounded bg-subtle px-2 py-1 font-mono text-[11px] text-ink-2">{JSON.stringify(list.find((v) => v.id === c.id)?.config ?? {}, null, 0)}</pre>
              ) : null}
            </div>
          );
        })}
        <label className="flex items-center gap-2">Frame stride <input className={`${field} w-16`} value={stride} onChange={(e) => setStride(e.target.value)} inputMode="numeric" /> <span className="text-ink-3">hand tracking and object detection read every Nth frame</span></label>
      </fieldset>
      {error ? <p className="text-error" role="alert">{error}</p> : null}
      <div className="flex items-center gap-3">
        <button type="submit" disabled={busy} className="h-[34px] rounded-md bg-ink px-4 text-xs font-semibold text-canvas disabled:opacity-50">Run auto annotation</button>
        <span className="text-ink-3">New events go to review; auto-accept rules apply to them as they arrive.</span>
      </div>
      {result ? (
        <div className="flex flex-col gap-1.5 rounded-md border border-line bg-subtle px-3 py-2" role="status" data-testid="auto-result">
          <p className="font-semibold">Queued {result.runs.length} run{result.runs.length === 1 ? "" : "s"} on {result.videos} video{result.videos === 1 ? "" : "s"}.</p>
          {Object.entries(result.setups).map(([k, s]) => <p key={k} className="font-mono text-[11px] text-ink-2">{k}: {String(s.adapter)} {JSON.stringify(s.config)}</p>)}
          {result.skipped.length ? (
            <ul className="text-ink-2">{result.skipped.map((s) => <li key={s.video.id}>Skipped {s.video.name}: {s.reason}</li>)}</ul>
          ) : null}
          <span className="text-ink-3">{formatDateTime(new Date().toISOString())} · progress in the runs table below</span>
        </div>
      ) : null}
    </form>
  );
}
