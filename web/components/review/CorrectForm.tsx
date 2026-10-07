"use client";

import { useState } from "react";
import type { MovementClassRead, MovementEventSummary } from "@/lib/api/types";

const FINGERS = ["thumb", "index", "middle", "ring", "pinky"] as const;

export interface CorrectionBody {
  class?: string;
  start_frame?: number;
  end_frame?: number;
  handedness?: "left" | "right";
  fingers?: string[];
  object_label?: string;
  clear_object?: boolean;
}

/**
 * Correct an event's class, frames, hand, fingers, or object. Only changed fields are sent; the server keeps
 * the prediction and stores the correction as a new version.
 */
export function CorrectForm({
  event,
  classes,
  onSubmit,
  onCancel,
}: {
  event: MovementEventSummary;
  classes: MovementClassRead[];
  onSubmit: (body: CorrectionBody) => Promise<string | null>;
  onCancel?: () => void;
}) {
  const [cls, setCls] = useState(event.movement_class.name);
  const [start, setStart] = useState(String(event.start_frame));
  const [end, setEnd] = useState(String(event.end_frame));
  const [hand, setHand] = useState(event.handedness);
  const [fingers, setFingers] = useState<string[]>(event.fingers);
  const [object, setObject] = useState(event.object_label ?? "");
  const [noObject, setNoObject] = useState(!event.object_label);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const body: CorrectionBody = {};
    if (cls !== event.movement_class.name) body.class = cls;
    const s = Number(start), en = Number(end);
    if (!Number.isInteger(s) || !Number.isInteger(en) || s < 0 || en < s) return setError("Frames: whole numbers, end at or after start.");
    if (s !== event.start_frame) body.start_frame = s;
    if (en !== event.end_frame) body.end_frame = en;
    if (hand !== event.handedness) body.handedness = hand as "left" | "right";
    if ([...fingers].sort().join() !== [...event.fingers].sort().join()) body.fingers = FINGERS.filter((f) => fingers.includes(f));
    if (noObject && event.object_label) body.clear_object = true;
    else if (!noObject && object.trim() && object.trim() !== event.object_label) body.object_label = object.trim();
    if (!Object.keys(body).length) return setError("Nothing changed. To keep the prediction as it is, accept it.");
    setBusy(true);
    setError(await onSubmit(body));
    setBusy(false);
  };

  const field = "h-[30px] rounded-md border border-line-strong bg-canvas px-2 text-xs";
  return (
    <form onSubmit={submit} className="flex flex-col gap-3 rounded-lg border border-human-line bg-human-bg/40 p-3 text-xs" aria-label="Correct event" data-testid="correct-form">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <label className="col-span-2 flex flex-col gap-1">
          <span className="font-semibold text-ink-2">Movement</span>
          <select className={field} value={cls} onChange={(e) => setCls(e.target.value)} name="class" autoFocus>
            {classes.filter((c) => c.active || c.name === event.movement_class.name).map((c) => <option key={c.id} value={c.name}>{c.label}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="font-semibold text-ink-2">Start frame</span>
          <input className={field} inputMode="numeric" value={start} onChange={(e) => setStart(e.target.value)} name="start_frame" />
        </label>
        <label className="flex flex-col gap-1">
          <span className="font-semibold text-ink-2">End frame</span>
          <input className={field} inputMode="numeric" value={end} onChange={(e) => setEnd(e.target.value)} name="end_frame" />
        </label>
        <label className="flex flex-col gap-1">
          <span className="font-semibold text-ink-2">Hand</span>
          <select className={field} value={hand} onChange={(e) => setHand(e.target.value)} name="handedness">
            <option value="left">Left</option>
            <option value="right">Right</option>
          </select>
        </label>
        <label className="col-span-2 flex flex-col gap-1 sm:col-span-3">
          <span className="font-semibold text-ink-2">Object</span>
          <span className="flex items-center gap-2">
            <input className={`${field} min-w-0 flex-1`} value={object} onChange={(e) => setObject(e.target.value)} disabled={noObject} placeholder="e.g. cup" name="object_label" />
            <label className="flex shrink-0 items-center gap-1"><input type="checkbox" checked={noObject} onChange={(e) => setNoObject(e.target.checked)} /> No object</label>
          </span>
        </label>
      </div>
      <fieldset className="flex flex-wrap items-center gap-3">
        <legend className="mb-1 font-semibold text-ink-2">Fingers</legend>
        {FINGERS.map((f) => (
          <label key={f} className="flex items-center gap-1 capitalize">
            <input type="checkbox" checked={fingers.includes(f)} onChange={(e) => setFingers((x) => (e.target.checked ? [...x, f] : x.filter((y) => y !== f)))} /> {f}
          </label>
        ))}
      </fieldset>
      {error ? <p className="text-error" role="alert">{error}</p> : null}
      <div className="flex gap-2">
        <button type="submit" disabled={busy} className="h-[30px] rounded-md bg-ink px-3 font-semibold text-canvas disabled:opacity-50">Save correction</button>
        {onCancel ? <button type="button" onClick={onCancel} className="h-[30px] rounded-md border border-line-strong px-3 font-medium hover:bg-hover">Cancel</button> : null}
        <span className="self-center text-ink-3">The prediction is kept; the correction becomes a new version.</span>
      </div>
    </form>
  );
}
