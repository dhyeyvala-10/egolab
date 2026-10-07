"use client";

import { useActionState, useMemo, useState } from "react";
import { FormMessage, inputClass } from "@/components/data/Field";
import { startRuns } from "@/lib/actions/cv";
import type { CvRunKind, Ref } from "@/lib/api/types";

export interface RunKindOption {
  kind: CvRunKind;
  label: string;
  hint?: string;
  checked?: boolean;
}

export const ALL_KINDS: RunKindOption[] = [
  { kind: "hand_tracking", label: "Hand tracking", checked: true },
  { kind: "object_detection", label: "Object detection", checked: true },
  { kind: "movement", label: "Movement classification", hint: "on the hand and object runs, when they finish", checked: true },
];

/** Pick ready videos and queue runs on each with the configured adapters. */
export function StartRunForm({
  videos,
  disabled,
  kinds = ALL_KINDS,
  verb = "Run",
  strides = true,
}: {
  videos: Ref[];
  disabled?: string | null;
  kinds?: RunKindOption[];
  verb?: string;
  strides?: boolean;
}) {
  const [state, action, pending] = useActionState(startRuns, {});
  const [picked, setPicked] = useState<Set<CvRunKind>>(() => new Set(kinds.filter((k) => k.checked).map((k) => k.kind)));
  const [q, setQ] = useState("");
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const shown = useMemo(() => videos.filter((v) => v.name.toLowerCase().includes(q.trim().toLowerCase())).slice(0, 100), [videos, q]);

  if (!videos.length) return <p className="py-2 text-xs text-ink-3">No ready videos yet. Upload a video first; it can be tracked once its proxy is built.</p>;
  return (
    <form action={action} className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <label htmlFor="run-q" className="text-xs font-semibold">Videos</label>
          <input id="run-q" className={inputClass} placeholder="Filter by file name" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        {strides ? (
          <div className="flex w-36 flex-col gap-1">
            <label htmlFor="run-stride" className="text-xs font-semibold">Process every</label>
            <select id="run-stride" name="stride" className={inputClass} defaultValue="1">
              <option value="1">frame</option>
              <option value="2">2nd frame</option>
              <option value="3">3rd frame</option>
              <option value="5">5th frame</option>
            </select>
          </div>
        ) : null}
      </div>
      {kinds.length > 1 ? (
        <fieldset className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
          <legend className="mb-1 font-semibold">Run</legend>
          {kinds.map((k) => (
            <label key={k.kind} className="flex items-center gap-1.5">
              <input
                type="checkbox"
                name="kind"
                value={k.kind}
                checked={picked.has(k.kind)}
                onChange={(e) => {
                  const next = new Set(picked);
                  if (e.target.checked) next.add(k.kind);
                  else next.delete(k.kind);
                  setPicked(next);
                }}
              />
              {k.label}
              {k.hint ? <span className="text-ink-3">({k.hint})</span> : null}
            </label>
          ))}
        </fieldset>
      ) : (
        kinds.map((k) => <input key={k.kind} type="hidden" name="kind" value={k.kind} />)
      )}
      <ul className="max-h-56 overflow-y-auto rounded-md border border-line" aria-label="Ready videos">
        {shown.map((v) => (
          <li key={v.id} className="border-b border-line last:border-b-0">
            <label className="flex cursor-pointer items-center gap-2 px-2.5 py-1.5 hover:bg-hover">
              <input
                type="checkbox"
                name="video_id"
                value={v.id}
                checked={chosen.has(v.id)}
                onChange={(e) => {
                  const next = new Set(chosen);
                  if (e.target.checked) next.add(v.id);
                  else next.delete(v.id);
                  setChosen(next);
                }}
              />
              <span className="truncate">{v.name}</span>
            </label>
          </li>
        ))}
        {!shown.length ? <li className="px-2.5 py-3 text-xs text-ink-3">No videos match.</li> : null}
      </ul>
      {/* Keep choices outside the filter submitted too. */}
      {[...chosen].filter((id) => !shown.some((v) => v.id === id)).map((id) => <input key={id} type="hidden" name="video_id" value={id} />)}
      <FormMessage error={disabled ?? state.error} ok={state.ok ? "Queued. The runs appear below." : undefined} />
      <button type="submit" disabled={pending || !chosen.size || !!disabled || (kinds.length > 1 && !picked.size)} className="h-8 self-start rounded-md bg-ink px-3 text-xs font-semibold text-canvas disabled:opacity-40">
        {pending ? "Queuing…" : `${verb}${chosen.size ? ` on ${chosen.size} video${chosen.size === 1 ? "" : "s"}` : ""}`}
      </button>
    </form>
  );
}
