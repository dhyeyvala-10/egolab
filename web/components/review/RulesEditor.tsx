"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { browserApi } from "@/lib/api/browser";
import type { BulkPreview, MovementClassRead, ReviewBatchRead, ReviewRuleRead } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";

function RuleRow({ rule, lead, onError }: { rule: ReviewRuleRead; lead: boolean; onError: (m: string | null) => void }) {
  const router = useRouter();
  const [value, setValue] = useState(String(rule.min_confidence));
  const save = async (patch: { min_confidence?: number; enabled?: boolean }) => {
    const res = await browserApi(`/review/rules/${rule.id}`, { method: "PATCH", body: patch });
    onError(res.ok ? null : res.message);
    router.refresh();
  };
  const remove = async () => {
    const res = await browserApi(`/review/rules/${rule.id}`, { method: "DELETE" });
    onError(res.ok ? null : res.message);
    router.refresh();
  };
  const threshold = Number(value);
  return (
    <tr className="border-t border-line" data-rule={rule.movement_class?.name ?? "default"}>
      <td className="px-3 py-2">
        {rule.movement_class ? <span className="font-medium">{rule.movement_class.label}</span> : <span className="font-medium">Default <span className="font-normal text-ink-3">(classes without their own rule)</span></span>}
      </td>
      <td className="px-3 py-2">
        {lead ? (
          <form className="flex items-center gap-1.5" onSubmit={(e) => { e.preventDefault(); if (threshold >= 0 && threshold <= 1) void save({ min_confidence: threshold }); }}>
            <span className="text-ink-3">≥</span>
            <input aria-label="Minimum confidence" value={value} onChange={(e) => setValue(e.target.value)} inputMode="decimal" className="h-7 w-16 rounded-md border border-line-strong px-1.5 font-mono text-xs" />
            {threshold !== rule.min_confidence ? <button type="submit" className="h-7 rounded-md border border-line-strong px-2 text-xs font-medium hover:bg-hover">Save</button> : null}
          </form>
        ) : (
          <span className="font-mono">≥ {rule.min_confidence.toFixed(2)}</span>
        )}
      </td>
      <td className="px-3 py-2">
        {lead ? (
          <label className="flex items-center gap-1.5"><input type="checkbox" checked={rule.enabled} onChange={(e) => void save({ enabled: e.target.checked })} /> {rule.enabled ? "On" : rule.movement_class ? "Off (never auto-accept this class)" : "Off"}</label>
        ) : rule.enabled ? "On" : "Off"}
      </td>
      <td className="px-3 py-2 text-right tabular-nums">{rule.accepted}</td>
      <td className="px-3 py-2 text-right">{lead ? <button type="button" onClick={() => void remove()} className="text-xs text-ink-3 underline hover:text-error">Remove</button> : null}</td>
    </tr>
  );
}

/**
 * Auto-accept rules: a confidence at or above which new predictions are confirmed with no person involved.
 * Accepted events are marked `auto_rule`, so datasets and metrics never mistake them for human review.
 */
export function RulesEditor({ rules, classes, lead }: { rules: ReviewRuleRead[]; classes: MovementClassRead[]; lead: boolean }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [cls, setCls] = useState("");
  const [threshold, setThreshold] = useState("0.9");
  const [preview, setPreview] = useState<BulkPreview | null>(null);
  const [applied, setApplied] = useState<ReviewBatchRead | null>(null);
  const hasDefault = rules.some((r) => !r.movement_class);
  const taken = new Set(rules.map((r) => r.movement_class?.name).filter(Boolean));

  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    const t = Number(threshold);
    if (!(t >= 0 && t <= 1)) return setError("Confidence is between 0 and 1.");
    const res = await browserApi<ReviewRuleRead>("/review/rules", { method: "POST", body: { class: cls || null, min_confidence: t } });
    setError(res.ok ? null : res.message);
    if (res.ok) setCls("");
    router.refresh();
  };
  const check = async () => {
    const res = await browserApi<BulkPreview>("/review/rules/apply/preview", { method: "POST", body: {} });
    if (!res.ok) return setError(res.message);
    setPreview(res.data);
  };
  const apply = async () => {
    const res = await browserApi<ReviewBatchRead>("/review/rules/apply", { method: "POST", body: {} });
    setPreview(null);
    if (!res.ok) return setError(res.message);
    setApplied(res.data);
    router.refresh();
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="overflow-x-auto rounded-lg border border-line">
        <table className="w-full min-w-[560px] border-collapse text-xs">
          <thead className="bg-subtle text-left text-ink-3">
            <tr><th className="px-3 py-2 font-semibold">Applies to</th><th className="px-3 py-2 font-semibold">Accept at confidence</th><th className="px-3 py-2 font-semibold">State</th><th className="px-3 py-2 text-right font-semibold">Accepted</th><th /></tr>
          </thead>
          <tbody>
            {rules.map((r) => <RuleRow key={`${r.id}:${r.min_confidence}`} rule={r} lead={lead} onError={setError} />)}
            {!rules.length ? <tr><td colSpan={5} className="px-3 py-6 text-center text-ink-3">No rules: every prediction waits for a person.</td></tr> : null}
          </tbody>
        </table>
      </div>
      {lead ? (
        <form onSubmit={add} className="flex flex-wrap items-end gap-2 text-xs" aria-label="Add a rule">
          <label className="flex flex-col gap-1">
            <span className="text-ink-2">Class</span>
            <select value={cls} onChange={(e) => setCls(e.target.value)} className="h-[30px] rounded-md border border-line-strong bg-canvas px-2" name="class">
              {!hasDefault ? <option value="">Default (all classes)</option> : <option value="" disabled>Choose a class</option>}
              {classes.filter((c) => !taken.has(c.name)).map((c) => <option key={c.id} value={c.name}>{c.label}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-ink-2">Accept at confidence ≥</span>
            <input value={threshold} onChange={(e) => setThreshold(e.target.value)} inputMode="decimal" className="h-[30px] w-20 rounded-md border border-line-strong px-2 font-mono" name="min_confidence" />
          </label>
          <button type="submit" disabled={hasDefault && !cls} className="h-[30px] rounded-md bg-ink px-3 font-semibold text-canvas disabled:opacity-50">Add rule</button>
          <span className="self-center text-ink-3">Rules apply to classification runs from now on. Events flagged for review are never auto-accepted.</span>
        </form>
      ) : null}
      {lead && rules.some((r) => r.enabled) ? (
        <div className="flex flex-wrap items-center gap-2 rounded-md border border-line bg-subtle px-3 py-2 text-xs">
          {preview ? (
            <>
              <span className="font-medium">{preview.count} pending prediction{preview.count === 1 ? "" : "s"} meet the rules now{preview.count ? ` (${Object.entries(preview.by_class).map(([k, n]) => `${k.replace(/_/g, " ")} ${n}`).join(", ")})` : ""}.</span>
              <button type="button" onClick={() => void apply()} disabled={!preview.count || preview.over_limit} className="h-7 rounded-md bg-ink px-2.5 font-semibold text-canvas disabled:opacity-50">Accept them</button>
              <button type="button" onClick={() => setPreview(null)} className="h-7 rounded-md border border-line-strong px-2.5 font-medium">Cancel</button>
            </>
          ) : applied ? (
            <span>Auto-accepted {applied.count} pending prediction{applied.count === 1 ? "" : "s"} as one batch ({formatDateTime(applied.created_at)}). Undo it below.</span>
          ) : (
            <>
              <span>Apply the rules to predictions already waiting for review?</span>
              <button type="button" onClick={() => void check()} className="h-7 rounded-md border border-line-strong px-2.5 font-medium hover:bg-hover">Check how many</button>
            </>
          )}
        </div>
      ) : null}
      {error ? <p className="text-xs text-error" role="alert">{error}</p> : null}
    </div>
  );
}

/** Bulk reviews and rule applications, newest first, each undoable once. */
export function BatchHistory({ batches, lead }: { batches: ReviewBatchRead[]; lead: boolean }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const undo = async (id: string) => {
    const res = await browserApi<ReviewBatchRead>(`/review/batches/${id}/undo`, { method: "POST" });
    setError(res.ok ? null : res.message);
    router.refresh();
  };
  if (!batches.length) return <p className="py-2 text-xs text-ink-3">No bulk reviews yet.</p>;
  return (
    <div className="flex flex-col gap-2">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[620px] border-collapse text-xs" data-testid="batches">
          <thead className="text-left text-ink-3"><tr><th className="py-1.5 font-semibold">When</th><th className="font-semibold">What</th><th className="font-semibold">Scope</th><th className="font-semibold">By</th><th className="text-right font-semibold">Events</th><th /></tr></thead>
          <tbody>
            {batches.map((b) => (
              <tr key={b.id} className="border-t border-line">
                <td className="py-1.5 tabular-nums">{formatDateTime(b.created_at)}</td>
                <td>{b.method === "auto_rule" ? "Rules applied" : b.action === "confirmed" ? "Bulk accept" : "Bulk reject"}</td>
                <td className="max-w-64 truncate font-mono text-[11px] text-ink-2">{Object.entries(b.filters).map(([k, v]) => `${k}=${Array.isArray(v) ? v.length > 2 ? `${v.length} ids` : v.join(",") : String(v)}`).join(" ") || "everything pending"}</td>
                <td>{b.actor?.name ?? "—"}</td>
                <td className="text-right tabular-nums">{b.count}</td>
                <td className="pl-3 text-right">
                  {b.undone_at ? <span className="text-ink-3">Undone ({b.undone_count})</span> : lead && b.count ? <button type="button" onClick={() => void undo(b.id)} className="font-medium underline">Undo</button> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {error ? <p className="text-xs text-error">{error}</p> : null}
    </div>
  );
}
