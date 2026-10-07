"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { apiFetch, type ApiError } from "@/lib/api/client";
import type { AssignmentStatus } from "@/lib/api/types";
import { getSession } from "@/lib/auth/session";
import type { FormState } from "./catalog";

async function token(): Promise<string> {
  const session = await getSession();
  if (session.status !== "authenticated") redirect("/auth/signed-out");
  return session.token;
}

function message(err: ApiError): string {
  if (err.kind === "unreachable") return "Can't reach the Ego Labs API. Check that it is running.";
  if (err.status === 403) return "Only reviewers and admins can assign work.";
  return err.message;
}

export async function createAssignment(_: FormState, form: FormData): Promise<FormState> {
  const tok = await token();
  const target = String(form.get("target") ?? "");
  const [kind, id] = target.split(":");
  const assignee = String(form.get("assignee_id") ?? "");
  if (!id || !assignee) return { error: "Choose what to assign and who to assign it to." };
  const note = String(form.get("note") ?? "").trim();
  const res = await apiFetch("/api/v1/assignments", {
    method: "POST",
    token: tok,
    body: { [kind === "video" ? "video_id" : "session_id"]: id, assignee_id: assignee, note: note || null },
  });
  if (!res.ok) return { error: message(res) };
  revalidatePath("/annotation/queue");
  return { ok: true };
}

export async function setAssignmentStatus(id: string, status: AssignmentStatus): Promise<FormState> {
  const res = await apiFetch(`/api/v1/assignments/${encodeURIComponent(id)}`, { method: "PATCH", token: await token(), body: { status } });
  if (!res.ok) return { error: message(res) };
  revalidatePath("/annotation/queue");
  return { ok: true };
}

export async function removeAssignment(id: string): Promise<FormState> {
  const res = await apiFetch(`/api/v1/assignments/${encodeURIComponent(id)}`, { method: "DELETE", token: await token() });
  if (!res.ok) return { error: message(res) };
  revalidatePath("/annotation/queue");
  return { ok: true };
}
