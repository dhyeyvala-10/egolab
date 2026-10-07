"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { apiFetch, type ApiError } from "@/lib/api/client";
import type { GrantableRole } from "@/lib/api/types";
import { getSession } from "@/lib/auth/session";

export interface AdminState {
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
  if (err.status === 403) return "Only the admin can do this.";
  return err.message;
}

async function send(path: string, method: "POST" | "PATCH" | "DELETE", body: unknown, revalidate: string[]): Promise<AdminState> {
  const res = await apiFetch(path, { method, body, token: await token() });
  if (!res.ok) return { error: message(res) };
  for (const p of revalidate) revalidatePath(p);
  return { ok: true };
}

export async function setRole(userId: string, role: GrantableRole): Promise<AdminState> {
  return send(`/api/v1/users/${encodeURIComponent(userId)}`, "PATCH", { role }, ["/settings"]);
}

export async function setActive(userId: string, isActive: boolean): Promise<AdminState> {
  return send(`/api/v1/users/${encodeURIComponent(userId)}`, "PATCH", { is_active: isActive }, ["/settings"]);
}

export async function reviewUpload(uploadId: string, allow: boolean, reason?: string): Promise<AdminState> {
  const path = `/api/v1/uploads/${encodeURIComponent(uploadId)}/${allow ? "approve" : "reject"}`;
  return send(path, "POST", allow ? undefined : { reason: reason || null }, ["/settings/requests", "/data/upload"]);
}

export async function reviewVideo(videoId: string, allow: boolean, reason?: string): Promise<AdminState> {
  const path = `/api/v1/requests/videos/${encodeURIComponent(videoId)}/${allow ? "allow" : "reject"}`;
  return send(path, "POST", allow ? undefined : { reason: reason || null }, ["/settings/requests"]);
}

/** Cancel an upload in progress (the uploader's own, or anyone's for the admin). */
export async function cancelUpload(uploadId: string): Promise<AdminState> {
  return send(`/api/v1/uploads/${encodeURIComponent(uploadId)}`, "DELETE", undefined, ["/data/upload"]);
}

const GB = 1000 ** 3; // decimal, as sizes are shown everywhere

export async function saveLimits(_: AdminState, form: FormData): Promise<AdminState> {
  const number = (key: string): number | null | "bad" => {
    const raw = String(form.get(key) ?? "").trim();
    if (raw === "") return null;
    const n = Number(raw);
    return Number.isFinite(n) && n > 0 ? n : "bad";
  };
  const size = number("upload_max_gb");
  const minutes = number("video_max_minutes");
  if (size === "bad" || minutes === "bad") return { error: "Limits must be positive numbers, or empty for no limit." };
  const processingBy = form.get("processing_by") === "editors" ? "editors" : "owner";
  return send(
    "/api/v1/settings/limits",
    "PATCH",
    {
      upload_max_bytes: size === null ? null : Math.round(size * GB),
      video_max_seconds: minutes === null ? null : minutes * 60,
      processing_by: processingBy,
    },
    ["/settings/limits"],
  );
}
