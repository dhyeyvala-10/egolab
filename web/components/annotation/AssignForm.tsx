"use client";

import { useActionState, useEffect, useRef } from "react";
import { FormMessage, inputClass } from "@/components/data/Field";
import { createAssignment } from "@/lib/actions/annotation";
import type { AssignableUser, Ref } from "@/lib/api/types";

/** Assign a session (all its videos) or a single video to someone. For reviewers and admins. */
export function AssignForm({ sessions, videos, people }: { sessions: Ref[]; videos: Ref[]; people: AssignableUser[] }) {
  const [state, action, pending] = useActionState(createAssignment, {});
  const form = useRef<HTMLFormElement>(null);
  useEffect(() => {
    if (state.ok) form.current?.reset();
  }, [state]);

  return (
    <form ref={form} action={action} className="flex flex-col gap-3">
      <div className="grid gap-3 md:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        <div className="flex min-w-0 flex-col gap-1">
          <label htmlFor="assign-target" className="text-xs font-semibold">Session or video</label>
          <select id="assign-target" name="target" required className={inputClass} defaultValue="">
            <option value="" disabled>Choose…</option>
            {sessions.length ? (
              <optgroup label="Sessions (every video in it)">
                {sessions.map((s) => <option key={s.id} value={`session:${s.id}`}>{s.name}</option>)}
              </optgroup>
            ) : null}
            {videos.length ? (
              <optgroup label="Single videos">
                {videos.map((v) => <option key={v.id} value={`video:${v.id}`}>{v.name}</option>)}
              </optgroup>
            ) : null}
          </select>
        </div>
        <div className="flex min-w-0 flex-col gap-1">
          <label htmlFor="assign-person" className="text-xs font-semibold">Assign to</label>
          <select id="assign-person" name="assignee_id" required className={inputClass} defaultValue="">
            <option value="" disabled>Choose…</option>
            {people.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.role}</option>)}
          </select>
        </div>
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="assign-note" className="text-xs font-semibold">Instructions <span className="font-normal text-ink-3">(optional)</span></label>
        <input id="assign-note" name="note" className={inputClass} maxLength={5000} placeholder="e.g. Label every reach and grasp" />
      </div>
      <FormMessage error={state.error} ok={state.ok ? "Assigned" : undefined} />
      <button type="submit" disabled={pending} className="h-8 self-start rounded-md bg-ink px-3 text-xs font-semibold text-canvas disabled:opacity-50">
        {pending ? "Assigning…" : "Assign"}
      </button>
    </form>
  );
}
