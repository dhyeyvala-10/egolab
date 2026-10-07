"use client";

import { useActionState, useEffect, useRef } from "react";
import { createDevice, type FormState } from "@/lib/actions/catalog";
import { Field, FormMessage } from "./Field";

export function DeviceForm() {
  const [state, action, pending] = useActionState<FormState, FormData>(createDevice, {});
  const form = useRef<HTMLFormElement>(null);
  useEffect(() => {
    if (state.ok) form.current?.reset();
  }, [state]);
  return (
    <form ref={form} action={action} className="flex flex-col gap-3">
      <Field id="name" label="Name" required placeholder="e.g. Aria-07" />
      <Field id="kind" label="Kind" placeholder="e.g. head-mounted camera, glasses, phone" />
      <Field id="serial" label="Serial number" />
      <FormMessage error={state.error} ok={state.ok ? "Device added" : undefined} />
      <div>
        <button type="submit" disabled={pending} className="h-[32px] rounded-md bg-ink px-3 font-semibold text-canvas hover:opacity-90 disabled:opacity-60">
          {pending ? "Adding…" : "Add device"}
        </button>
      </div>
    </form>
  );
}
