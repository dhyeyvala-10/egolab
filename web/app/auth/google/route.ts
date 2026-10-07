import { NextResponse, type NextRequest } from "next/server";
import { api } from "@/lib/api/client";
import { appUrl, callbackUrl, challengeFor, GOOGLE_COOKIE, GOOGLE_COOKIE_MAX_AGE, randomToken, type GoogleAttempt } from "@/lib/auth/google";
import { cookieOptions, safeNext } from "@/lib/auth/session";

/** "Continue with Google": send the browser to Google's sign-in with a fresh state and PKCE challenge. */
export async function GET(request: NextRequest) {
  const failed = (error: string) => NextResponse.redirect(appUrl(request, `/login?error=${error}`));
  const config = await api.googleConfig();
  if (!config.ok) return failed("unavailable");
  if (!config.data.enabled || !config.data.client_id) return failed("not_configured");

  const attempt: GoogleAttempt = {
    state: randomToken(),
    verifier: randomToken(48),
    next: safeNext(request.nextUrl.searchParams.get("next"), ""),
  };
  const google = new URL(config.data.authorize_url);
  google.search = new URLSearchParams({
    client_id: config.data.client_id,
    redirect_uri: callbackUrl(request),
    response_type: "code",
    scope: "openid email profile",
    state: attempt.state,
    code_challenge: await challengeFor(attempt.verifier),
    code_challenge_method: "S256",
    prompt: "select_account",
  }).toString();

  const res = NextResponse.redirect(google);
  res.cookies.set(GOOGLE_COOKIE, JSON.stringify(attempt), { ...cookieOptions(GOOGLE_COOKIE_MAX_AGE), path: "/auth/google" });
  return res;
}
