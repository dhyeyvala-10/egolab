"use client";

import { useActionState } from "react";
import { addSessionToDataset, removeSessionFromDataset, type FormState } from "@/lib/actions/catalog";
import type { Ref } from "@/lib/api/types";
import { FormMessage, inputClass } from "./Field";

export function DatasetMembership({ sessionId, member, all }: { sessionId: string; member: Ref[]; all: Ref[] }) {
  const [state, action, pending] = useActionState<FormState, FormData>(addSessionToDataset, {});
  const available = all.filter((d) => !member.some((m) => m.id === d.id));
  return (
    <div className="flex flex-col gap-3 py-1">
      {member.length === 0 ? (
        <p className="text-ink-3">Not in any dataset yet.</p>
      ) : (
        <ul className="flex flex-wrap gap-1.5">
          {member.map((d) => (
            <li key={d.id} className="inline-flex items-center gap-1 rounded-md border border-line bg-subtle py-0.5 pl-2 pr-1 text-xs">
              {d.name}
              <form action={removeSessionFromDataset}>
                <input type="hidden" name="session_id" value={sessionId} />
                <input type="hidden" name="dataset_id" value={d.id} />
                <button type="submit" aria-label={`Remove from ${d.name}`} className="rounded px-1 text-ink-3 hover:bg-hover hover:text-ink">
                  ×
                </button>
              </form>
            </li>
          ))}
        </ul>
      )}
      <form action={action} className="flex flex-col gap-2">
        <input type="hidden" name="session_id" value={sessionId} />
        <div className="flex gap-2">
          <select name="dataset_id" aria-label="Dataset" className={`${inputClass} flex-1`} defaultValue="">
            <option value="">{available.length ? "Choose a dataset…" : "No other datasets"}</option>
            {available.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
          <button type="submit" disabled={pending} className="h-[32px] rounded-md border border-line-strong px-3 font-medium hover:bg-hover disabled:opacity-60">
            Add
          </button>
        </div>
        <input name="new_dataset" aria-label="New dataset name" placeholder="…or type a name to create a dataset" className={inputClass} />
        <FormMessage error={state.error} />
      </form>
    </div>
  );
}
