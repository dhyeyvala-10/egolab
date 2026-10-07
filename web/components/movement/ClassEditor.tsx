"use client";

import { useActionState, useState, useTransition } from "react";
import { FormMessage, inputClass } from "@/components/data/Field";
import { createMovementClass, updateMovementClass } from "@/lib/actions/cv";
import type { MovementClassRead } from "@/lib/api/types";
import { cn } from "@/lib/cn";

function Row({ c, canEdit }: { c: MovementClassRead; canEdit: boolean }) {
  const [editing, setEditing] = useState(false);
  const [label, setLabel] = useState(c.label);
  const [description, setDescription] = useState(c.description);
  const [pending, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const save = (patch: { label?: string; description?: string; active?: boolean }) =>
    start(async () => {
      const res = await updateMovementClass(c.id, patch);
      setError(res.error ?? null);
      if (!res.error) setEditing(false);
    });
  return (
    <tr className={cn("border-t border-line align-top", !c.active && "text-ink-3")} data-class={c.name}>
      <td className="px-3 py-2">
        {editing ? (
          <input aria-label={`Label for ${c.name}`} className={inputClass} value={label} onChange={(e) => setLabel(e.target.value)} />
        ) : (
          <span className="font-medium">{c.label}</span>
        )}
        <div className="font-mono text-[11px] text-ink-3">{c.name}</div>
      </td>
      <td className="px-3 py-2 text-ink-2">
        {editing ? (
          <textarea aria-label={`Description of ${c.name}`} className={cn(inputClass, "h-16 w-full py-1")} value={description} onChange={(e) => setDescription(e.target.value)} />
        ) : (
          c.description || <span className="text-ink-3">—</span>
        )}
        {error ? <p className="mt-1 text-xs text-error">{error}</p> : null}
      </td>
      <td className="px-3 py-2 text-xs">{c.builtin ? "Built in" : "Custom"}{c.requires_object ? " · needs an object" : ""}</td>
      <td className="px-3 py-2 text-right tabular-nums">{c.events}</td>
      <td className="px-3 py-2">
        {canEdit ? (
          <div className="flex flex-wrap justify-end gap-1.5 text-xs">
            {editing ? (
              <>
                <button type="button" disabled={pending || !label.trim()} onClick={() => save({ label: label.trim(), description: description.trim() })} className="h-7 rounded-md bg-ink px-2.5 font-semibold text-canvas disabled:opacity-50">Save</button>
                <button type="button" onClick={() => { setEditing(false); setLabel(c.label); setDescription(c.description); }} className="h-7 rounded-md border border-line-strong px-2.5 font-medium hover:bg-hover">Cancel</button>
              </>
            ) : (
              <button type="button" onClick={() => setEditing(true)} className="h-7 rounded-md border border-line-strong px-2.5 font-medium hover:bg-hover">Edit</button>
            )}
            <label className="flex items-center gap-1.5 px-1">
              <input type="checkbox" checked={c.active} disabled={pending} onChange={(e) => save({ active: e.target.checked })} />
              Active
            </label>
          </div>
        ) : (
          <span className="text-xs">{c.active ? "Active" : "Off"}</span>
        )}
      </td>
    </tr>
  );
}

/** The movement taxonomy: the spec's classes plus custom ones. Leads (admins, reviewers) edit it. */
export function ClassEditor({ classes, canEdit }: { classes: MovementClassRead[]; canEdit: boolean }) {
  const [state, action, pending] = useActionState(createMovementClass, {});
  return (
    <div className="flex flex-col gap-4">
      <div className="overflow-x-auto rounded-md border border-line">
        <table className="w-full border-collapse text-[13px]">
          <caption className="sr-only">Movement classes</caption>
          <thead className="bg-subtle text-left text-xs text-ink-3">
            <tr>
              <th className="px-3 py-2 font-semibold">Class</th>
              <th className="px-3 py-2 font-semibold">Description</th>
              <th className="px-3 py-2 font-semibold">Kind</th>
              <th className="px-3 py-2 text-right font-semibold">Events</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody>{classes.map((c) => <Row key={c.id} c={c} canEdit={canEdit} />)}</tbody>
        </table>
      </div>
      {canEdit ? (
        <form action={action} className="flex flex-col gap-3 rounded-md border border-line p-3">
          <h2 className="text-sm font-semibold">Add a custom class</h2>
          <div className="grid gap-3 md:grid-cols-[180px_220px_minmax(0,1fr)]">
            <label className="flex flex-col gap-1 text-xs font-semibold">Name<input name="name" required pattern="[a-z][a-z0-9_]{1,63}" placeholder="screw_in" className={cn(inputClass, "font-mono")} /></label>
            <label className="flex flex-col gap-1 text-xs font-semibold">Label<input name="label" required maxLength={120} placeholder="Screw in" className={inputClass} /></label>
            <label className="flex flex-col gap-1 text-xs font-semibold">Description<input name="description" maxLength={2000} placeholder="Turning a screw into a hole." className={inputClass} /></label>
          </div>
          <label className="flex items-center gap-1.5 text-xs"><input type="checkbox" name="requires_object" /> Involves an object</label>
          <FormMessage error={state.error} ok={state.ok ? "Added. Annotators can use it now; a classifier that emits this name records it." : undefined} />
          <button type="submit" disabled={pending} className="h-8 self-start rounded-md bg-ink px-3 text-xs font-semibold text-canvas disabled:opacity-40">{pending ? "Adding…" : "Add class"}</button>
        </form>
      ) : null}
    </div>
  );
}
