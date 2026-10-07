import type { NextRequest } from "next/server";

/**
 * Sign-in with Google (authorization code flow with PKCE). `/auth/google` sends people to Google with a
 * random `state` and a PKCE challenge, keeping both in a short-lived httpOnly cookie; Google sends them back
 * to `/auth/google/callback`, which checks the state and has the API finish signing in.
 */

/** httpOnly cookie holding the sign-in attempt's state, PKCE verifier and destination (10 minutes). */
export const GOOGLE_COOKIE = "egolabs_google";
export const GOOGLE_COOKIE_MAX_AGE = 600;

/** Where signing in lands when no page asked for it. */
export const AFTER_SIGN_IN = "/dashboard";

export interface GoogleAttempt {
  state: string;
  verifier: string;
  next: string;
}

function base64url(bytes: Uint8Array): string {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function randomToken(bytes = 32): string {
  return base64url(crypto.getRandomValues(new Uint8Array(bytes)));
}

/** The S256 PKCE challenge for a verifier. */
export async function challengeFor(verifier: string): Promise<string> {
  return base64url(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier))));
}

/**
 * The web app's own address, as the browser sees it: PUBLIC_WEB_URL when set, else the Host the browser
 * sent (`request.url` can name the server's own address instead, e.g. localhost for 127.0.0.1, and the
 * sign-in cookie only comes back to the host that set it). Google must list `<this>/auth/google/callback`
 * as a redirect URI.
 */
export function publicOrigin(request: NextRequest): string {
  const configured = process.env.PUBLIC_WEB_URL?.trim().replace(/\/+$/, "");
  if (configured) return configured;
  const host = request.headers.get("x-forwarded-host")?.split(",")[0].trim() || request.headers.get("host");
  const proto = request.headers.get("x-forwarded-proto")?.split(",")[0].trim() || request.nextUrl.protocol.replace(/:$/, "");
  return host ? `${proto}://${host}` : request.nextUrl.origin;
}

/** A page of this app, on the address the browser is using. */
export function appUrl(request: NextRequest, path: string): URL {
  return new URL(path, publicOrigin(request));
}

export function callbackUrl(request: NextRequest): string {
  return `${publicOrigin(request)}/auth/google/callback`;
}

export function readAttempt(raw: string | undefined): GoogleAttempt | null {
  if (!raw) return null;
  try {
    const v = JSON.parse(raw) as Partial<GoogleAttempt>;
    return typeof v.state === "string" && typeof v.verifier === "string" && typeof v.next === "string"
      ? { state: v.state, verifier: v.verifier, next: v.next }
      : null;
  } catch {
    return null;
  }
}

/** Why signing in stopped, as the login page shows it (`/login?error=<key>`). */
export const SIGN_IN_ERRORS = {
  not_configured: "Google sign-in isn't set up yet. An admin needs to set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET for the API.",
  unavailable: "Can't reach Ego Labs right now. Try again in a moment.",
  cancelled: "Sign-in was cancelled. Choose a Google account to continue.",
  expired: "That sign-in took too long or was opened in another tab. Try again.",
  unverified: "Your Google account's email address isn't verified. Verify it with Google, then try again.",
  deactivated: "This account is deactivated. Ask an admin to turn it back on.",
  linked: "This email belongs to an account linked to a different Google account.",
  failed: "Google sign-in didn't go through. Try again.",
} as const;

export type SignInError = keyof typeof SIGN_IN_ERRORS;

export function signInError(key: unknown): string | undefined {
  return typeof key === "string" && key in SIGN_IN_ERRORS ? SIGN_IN_ERRORS[key as SignInError] : undefined;
}
