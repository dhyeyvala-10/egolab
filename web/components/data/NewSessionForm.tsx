"use client";

import { useActionState } from "react";
import { createSession, type FormState } from "@/lib/actions/catalog";
import { Field, FormMessage, inputClass } from "./Field";

export function NewSessionForm({ nextName, today, operators, devices }: { nextName: string; today: string; operators: string[]; devices: string[] }) {
  const [state, action, pending] = useActionState<FormState, FormData>(createSession, {});
  return (
    <form action={action} className="flex max-w-[860px] flex-col gap-5">
      <FormMessage error={state.error} />
      <section className="grid gap-4 rounded-lg border border-line p-4 sm:grid-cols-2">
        <Field id="capture_date" label="Capture date" type="date" defaultValue={today} hint={<>The name is generated from this date: next is <span className="font-mono">{nextName}</span> for today.</>} />
        <div className="hidden sm:block" />
        <Field id="started_at" label="Start time (UTC)" type="datetime-local" />
        <Field id="ended_at" label="End time (UTC)" type="datetime-local" />
        <Field id="operator" label="Operator" list="operators" placeholder="Name — picks an existing operator or adds one" autoComplete="off" />
        <Field id="device" label="Device" list="devices" placeholder="e.g. Aria-07 — picks or adds a device" autoComplete="off" />
        <datalist id="operators">{operators.map((o) => <option key={o} value={o} />)}</datalist>
        <datalist id="devices">{devices.map((d) => <option key={d} value={d} />)}</datalist>
        <Field id="task" label="Task" placeholder="e.g. make tea, assemble chair" />
        <Field id="environment" label="Environment" placeholder="e.g. kitchen, workshop, warehouse" />
        <Field id="location" label="Location" placeholder="e.g. Lab B, Home 3" />
      </section>
      <section className="grid gap-4 rounded-lg border border-line p-4 sm:grid-cols-2">
        <h2 className="text-[13px] font-semibold sm:col-span-2">Capture conditions</h2>
        <Field id="cond_lighting" label="Lighting">
          <select id="cond_lighting" name="cond_lighting" className={inputClass} defaultValue="">
            <option value="">Not recorded</option>
            <option value="bright">Bright</option>
            <option value="normal">Normal</option>
            <option value="low">Low</option>
            <option value="mixed">Mixed</option>
          </select>
        </Field>
        <Field id="cond_clutter" label="Clutter">
          <select id="cond_clutter" name="cond_clutter" className={inputClass} defaultValue="">
            <option value="">Not recorded</option>
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
          </select>
        </Field>
        <Field id="cond_camera_mount" label="Camera mount" placeholder="e.g. head, chest, glasses" />
        <Field id="cond_hands_visible" label="Hands visible">
          <select id="cond_hands_visible" name="cond_hands_visible" className={inputClass} defaultValue="">
            <option value="">Not recorded</option>
            <option value="both">Both</option>
            <option value="right">Right only</option>
            <option value="left">Left only</option>
            <option value="intermittent">Intermittent</option>
          </select>
        </Field>
        <Field id="cond_other" label="Other conditions" placeholder="Anything else worth filtering on later" />
        <div className="flex min-w-0 flex-col gap-1 sm:col-span-2">
          <label htmlFor="notes" className="text-xs font-semibold">Notes</label>
          <textarea id="notes" name="notes" rows={3} className="w-full rounded-md border border-line-strong bg-canvas p-2.5 focus:border-ink focus:outline-none" />
        </div>
      </section>
      <div>
        <button type="submit" disabled={pending} className="h-[32px] rounded-md bg-ink px-4 font-semibold text-canvas hover:opacity-90 disabled:opacity-60">
          {pending ? "Creating…" : "Create session"}
        </button>
      </div>
    </form>
  );
}
