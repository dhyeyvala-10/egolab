import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { cache } from "react";
import { api, apiUrl } from "@/lib/api/client";
import type { UserRead } from "@/lib/api/types";
import { SESSION_COOKIE } from "./constants";

export { SESSION_COOKIE };

export type SessionState =
  | { status: "authenticated"; user: UserRead; token: string }
  | { status: "anonymous" }
  | { status: "unavailable"; message: string };

/** Resolve the signed-in user once per request by asking the API (the API is the source of truth). */
export const getSession = cache(async (): Promise<SessionState> => {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!token) return { status: "anonymous" };
  const res = await api.me(token);
  if (res.ok) return { status: "authenticated", user: res.data, token };
  if (res.kind === "http" && (res.status === 401 || res.status === 403)) return { status: "anonymous" };
  return {
    status: "unavailable",
    message: res.kind === "unreachable" ? `Can't reach the Ego Labs API at ${apiUrl()} (${res.message}).` : res.message,
  };
});

/**
 * For pages inside the app shell. Redirects to sign-in when there is no valid session; returns null when
 * the API is unavailable (the layout renders that state). Pages render in parallel with the layout, so
 * every page that loads data calls this itself.
 */
export async function requireSession(next = "/"): Promise<Extract<SessionState, { status: "authenticated" }> | null> {
  const session = await getSession();
  if (session.status === "anonymous") redirect(`/auth/signed-out?next=${encodeURIComponent(safeNext(next))}`);
  return session.status === "authenticated" ? session : null;
}

/** Only allow same-site relative redirects after sign-in. */
export function safeNext(next: unknown, fallback = "/"): string {
  return typeof next === "string" && next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/\\")
    ? next
    : fallback;
}

export function cookieOptions(maxAgeSeconds: number) {
  return {
    httpOnly: true,
    sameSite: "lax" as const,
    // Set COOKIE_SECURE=true when serving over HTTPS.
    secure: process.env.COOKIE_SECURE === "true",
    path: "/",
    maxAge: maxAgeSeconds,
  };
}
