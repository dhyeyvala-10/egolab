"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { apiFetch, type ApiError } from "@/lib/api/client";
import type { CvRunKind, CvRunSummary, MovementClassRead, MovementEventDetail } from "@/lib/api/types";
import { getSession } from "@/lib/auth/session";
import type { FormState } from "./catalog";

const KINDS: CvRunKind[] = ["hand_tracking", "object_detection", "movement"];

async function token(): Promise<string> {
  const session = await getSession();
  if (session.status !== "authenticated") redirect("/auth/signed-out");
  return session.token;
}

function message(err: ApiError, action = "start runs"): string {
  if (err.kind === "unreachable") return "Can't reach the Ego Labs API. Check that it is running.";
  if (err.status === 403) return `Your role can't ${action}. Ask an admin for the right access.`;
  return err.message;
}

function revalidateCv() {
  for (const path of ["/cv/hands", "/cv/fingers", "/cv/objects", "/cv/movements"]) revalidatePath(path);
}

/**
 * Queue model runs on the chosen videos. The form sends `kind` for each kind to run (default: all three —
 * hand tracking and object detection, then movement classification on their output).
 */
export async function startRuns(_: FormState, form: FormData): Promise<FormState> {
  const t = await token();
  const videoIds = form.getAll("video_id").map(String).filter(Boolean);
  if (!videoIds.length) return { error: "Choose at least one video." };
  const kinds = form.getAll("kind").map(String).filter((k): k is CvRunKind => KINDS.includes(k as CvRunKind));
  if (!kinds.length) return { error: "Choose what to run." };
  const stride = Math.max(1, Math.min(30, Number(form.get("stride") ?? 1) || 1));
  const res = await apiFetch<CvRunSummary[]>("/api/v1/cv/runs", { method: "POST", token: t, body: { video_ids: videoIds, stride, kinds } });
  if (!res.ok) return { error: message(res) };
  revalidateCv();
  return { ok: true };
}

/** Phase 3 name: hand tracking and what follows it by default. */
export const startHandTracking = startRuns;

export async function createMovementClass(_: FormState, form: FormData): Promise<FormState> {
  const t = await token();
  const body = {
    name: String(form.get("name") ?? "").trim(),
    label: String(form.get("label") ?? "").trim(),
    description: String(form.get("description") ?? "").trim(),
    requires_object: form.get("requires_object") === "on",
  };
  const res = await apiFetch<MovementClassRead>("/api/v1/movement/classes", { method: "POST", token: t, body });
  if (!res.ok) return { error: message(res, "edit movement classes") };
  revalidatePath("/cv/movements/classes");
  return { ok: true };
}

export async function updateMovementClass(id: string, patch: { label?: string; description?: string; active?: boolean }): Promise<FormState> {
  const t = await token();
  const res = await apiFetch<MovementClassRead>(`/api/v1/movement/classes/${encodeURIComponent(id)}`, { method: "PATCH", token: t, body: patch });
  if (!res.ok) return { error: message(res, "edit movement classes") };
  revalidatePath("/cv/movements/classes");
  revalidatePath("/cv/movements");
  return { ok: true };
}

export async function reviewEvent(id: string, status: "auto_detected" | "needs_review" | "confirmed" | "rejected"): Promise<FormState> {
  const t = await token();
  const res = await apiFetch<MovementEventDetail>(`/api/v1/movement/events/${encodeURIComponent(id)}`, { method: "PATCH", token: t, body: { status } });
  if (!res.ok) return { error: message(res, "review events") };
  revalidatePath(`/cv/movements/events/${id}`);
  revalidatePath("/cv/movements");
  return { ok: true };
}
