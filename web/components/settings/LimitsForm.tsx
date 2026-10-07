"use client";

import { useActionState } from "react";
import { Field, FormMessage, inputClass } from "@/components/data/Field";
import type { Limits } from "@/lib/api/types";
import { saveLimits } from "@/lib/actions/admin";

const GB = 1000 ** 3; // decimal, as sizes are shown everywhere

/** Shown in the form: whole numbers without trailing zeros. */
const trim = (n: number) => String(Number(n.toFixed(3)));

export function LimitsForm({ limits }: { limits: Limits }) {
  const [state, action, pending] = useActionState(saveLimits, {});
  return (
    <form action={action} className="flex max-w-[640px] flex-col gap-4 rounded-lg border border-line p-4">
      <Field
        id="upload_max_gb"
        label="Largest upload without asking you (GB)"
        type="number"
        min="0.001"
        step="any"
        inputMode="decimal"
        placeholder="No limit"
        defaultValue={limits.upload_max_bytes ? trim(limits.upload_max_bytes / GB) : ""}
        hint="A bigger file waits for you on Requests before any of it is sent. Empty: no limit. Your own uploads never wait."
      />
      <Field
        id="video_max_minutes"
        label="Longest video processed without asking you (minutes)"
        type="number"
        min="0.1"
        step="any"
        inputMode="decimal"
        placeholder="No limit"
        defaultValue={limits.video_max_seconds ? trim(limits.video_max_seconds / 60) : ""}
        hint="A longer video is stored, but nothing processes it until you allow it on Requests. Empty: no limit."
      />
      <div className="flex min-w-0 flex-col gap-1">
        <label htmlFor="processing_by" className="text-xs font-semibold">Who can start processing</label>
        <select id="processing_by" name="processing_by" className={inputClass} defaultValue={limits.processing_by ?? "owner"}>
          <option value="owner">Only me</option>
          <option value="editors">Me, annotators, and reviewers</option>
        </select>
        <span className="text-xs text-ink-3">
          Pipelines and their runs and schedules, tracking runs, auto annotation, and dataset versions and exports. Pipelines
          you set to run on new uploads keep running either way.
        </span>
      </div>
      <FormMessage error={state.error} ok={state.ok ? "Saved" : undefined} />
      <div>
        <button type="submit" disabled={pending} className="h-9 rounded-md bg-ink px-4 text-sm font-semibold text-ground hover:opacity-90 disabled:opacity-50">
          {pending ? "Saving…" : "Save limits"}
        </button>
      </div>
    </form>
  );
}
