"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { apiFetch, type ApiError } from "@/lib/api/client";
import type { DatasetSummary, DeviceSummary, OperatorRead, SessionDetail } from "@/lib/api/types";
import { getSession } from "@/lib/auth/session";

export interface FormState {
  error?: string;
  ok?: boolean;
}

async function token(): Promise<string> {
  const session = await getSession();
  if (session.status !== "authenticated") redirect("/auth/signed-out");
  return session.token;
}

function message(err: ApiError): string {
  if (err.kind === "unreachable") return "Can't reach the Ego Labs API. Check that it is running.";
  if (err.status === 403) return "Your role can't make changes. Ask an admin for annotator or reviewer access.";
  return err.message;
}

const text = (form: FormData, key: string) => {
  const value = String(form.get(key) ?? "").trim();
  return value === "" ? null : value;
};

/** Resolve an operator or device typed by name: reuse an existing one, or create it. */
async function findOrCreate(tok: string, kind: "operators" | "devices", name: string | null): Promise<string | null | ApiError> {
  if (!name) return null;
  const list = await apiFetch<{ items: (OperatorRead | DeviceSummary)[] }>(`/api/v1/${kind}?limit=${kind === "operators" ? 500 : 200}`, { token: tok });
  if (!list.ok) return list;
  const match = list.data.items.find((item) => item.name.toLowerCase() === name.toLowerCase());
  if (match) return match.id;
  const created = await apiFetch<{ id: string }>(`/api/v1/${kind}`, { method: "POST", body: { name }, token: tok });
  return created.ok ? created.data.id : created;
}

function localToIso(value: string | null): string | null {
  // <input type="datetime-local"> has no zone; the form labels these times as UTC.
  return value ? new Date(`${value}:00Z`).toISOString() : null;
}

export async function createSession(_: FormState, form: FormData): Promise<FormState> {
  const tok = await token();
  const operator = await findOrCreate(tok, "operators", text(form, "operator"));
  if (operator && typeof operator === "object") return { error: message(operator) };
  const device = await findOrCreate(tok, "devices", text(form, "device"));
  if (device && typeof device === "object") return { error: message(device) };

  const conditions: Record<string, string> = {};
  for (const key of ["lighting", "clutter", "camera_mount", "hands_visible"]) {
    const value = text(form, `cond_${key}`);
    if (value) conditions[key] = value;
  }
  const extra = text(form, "cond_other");
  if (extra) conditions.other = extra;

  const res = await apiFetch<SessionDetail>("/api/v1/sessions", {
    method: "POST",
    token: tok,
    body: {
      capture_date: text(form, "capture_date"),
      operator_id: operator,
      device_id: device,
      started_at: localToIso(text(form, "started_at")),
      ended_at: localToIso(text(form, "ended_at")),
      environment: text(form, "environment"),
      task: text(form, "task"),
      location: text(form, "location"),
      capture_conditions: conditions,
      notes: text(form, "notes"),
    },
  });
  if (!res.ok) return { error: message(res) };
  revalidatePath("/data/sessions");
  redirect(`/data/sessions/${res.data.id}`);
}

export async function createDevice(_: FormState, form: FormData): Promise<FormState> {
  const tok = await token();
  const res = await apiFetch<DeviceSummary>("/api/v1/devices", {
    method: "POST",
    token: tok,
    body: { name: text(form, "name"), kind: text(form, "kind"), serial: text(form, "serial") },
  });
  if (!res.ok) return { error: message(res) };
  revalidatePath("/data/devices");
  return { ok: true };
}

export async function addSessionToDataset(_: FormState, form: FormData): Promise<FormState> {
  const tok = await token();
  const sessionId = String(form.get("session_id"));
  let datasetId = text(form, "dataset_id");
  const newName = text(form, "new_dataset");
  if (!datasetId && newName) {
    const created = await apiFetch<DatasetSummary>("/api/v1/datasets", { method: "POST", token: tok, body: { name: newName } });
    if (!created.ok) return { error: message(created) };
    datasetId = created.data.id;
  }
  if (!datasetId) return { error: "Choose a dataset or type a name for a new one." };
  const res = await apiFetch(`/api/v1/datasets/${datasetId}/sessions`, { method: "POST", token: tok, body: { session_id: sessionId } });
  if (!res.ok) return { error: message(res) };
  revalidatePath(`/data/sessions/${sessionId}`);
  return { ok: true };
}

export async function removeSessionFromDataset(form: FormData): Promise<void> {
  const tok = await token();
  const sessionId = String(form.get("session_id"));
  await apiFetch(`/api/v1/datasets/${String(form.get("dataset_id"))}/sessions/${sessionId}`, { method: "DELETE", token: tok });
  revalidatePath(`/data/sessions/${sessionId}`);
}

export async function moveVideo(_: FormState, form: FormData): Promise<FormState> {
  const tok = await token();
  const videoId = String(form.get("video_id"));
  const sessionId = text(form, "session_id");
  const res = await apiFetch(`/api/v1/videos/${videoId}`, { method: "PATCH", token: tok, body: { session_id: sessionId } });
  if (!res.ok) return { error: message(res) };
  revalidatePath(`/data/videos/${videoId}`);
  return { ok: true };
}
