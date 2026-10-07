"use client";

import { useActionState } from "react";
import { moveVideo, type FormState } from "@/lib/actions/catalog";
import type { Ref } from "@/lib/api/types";

export function MoveVideoForm({ videoId, sessionId, sessions }: { videoId: string; sessionId: string | null; sessions: Ref[] }) {
  const [state, action, pending] = useActionState<FormState, FormData>(moveVideo, {});
  return (
    <form action={action} className="flex flex-col gap-2">
      <input type="hidden" name="video_id" value={videoId} />
      <label htmlFor="move-session" className="text-xs font-semibold">
        Session
      </label>
      <div className="flex gap-2">
        <select
          id="move-session"
          name="session_id"
          defaultValue={sessionId ?? ""}
          className="h-[30px] min-w-0 flex-1 rounded-md border border-line-strong bg-canvas px-2"
        >
          <option value="">Unassigned</option>
          {sessions.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
        <button type="submit" disabled={pending} className="h-[30px] rounded-md border border-line-strong px-3 font-medium hover:bg-hover disabled:opacity-60">
          {pending ? "Saving…" : "Move"}
        </button>
      </div>
      {state.error ? <p role="alert" className="text-xs text-error">{state.error}</p> : null}
      {state.ok ? <p role="status" className="text-xs text-success">Saved</p> : null}
    </form>
  );
}
