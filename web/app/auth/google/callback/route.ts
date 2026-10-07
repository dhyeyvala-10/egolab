import { NextResponse, type NextRequest } from "next/server";
import { api } from "@/lib/api/client";
import { AFTER_SIGN_IN, appUrl, callbackUrl, GOOGLE_COOKIE, readAttempt, type SignInError } from "@/lib/auth/google";
import { cookieOptions, safeNext, SESSION_COOKIE } from "@/lib/auth/session";

/** Google sends the browser back here with a one-time code: check the state, then sign in through the API. */
export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams;
  const attempt = readAttempt(request.cookies.get(GOOGLE_COOKIE)?.value);
  const finish = (to: URL) => {
    const res = NextResponse.redirect(to);
    res.cookies.set(GOOGLE_COOKIE, "", { ...cookieOptions(0), path: "/auth/google" });
    return res;
  };
  const failed = (error: SignInError) => finish(appUrl(request, `/login?error=${error}`));

  if (params.get("error")) return failed(params.get("error") === "access_denied" ? "cancelled" : "failed");
  const code = params.get("code");
  if (!attempt || !code || params.get("state") !== attempt.state) return failed("expired");

  const client: Record<string, string> = {};
  const ip = request.headers.get("cf-connecting-ip") ?? request.headers.get("x-forwarded-for")?.split(",")[0].trim();
  if (ip) client["x-forwarded-for"] = ip;
  const agent = request.headers.get("user-agent");
  if (agent) client["user-agent"] = agent;
  const res = await api.googleSignIn(code, callbackUrl(request), attempt.verifier, client);
  if (!res.ok) {
    if (res.kind === "unreachable") return failed("unavailable");
    if (res.status === 403) return failed("deactivated");
    if (res.status === 409) return failed("linked");
    if (res.status === 503) return failed("not_configured");
    return failed(res.message.includes("isn't verified") ? "unverified" : "failed");
  }
  const out = finish(appUrl(request, safeNext(attempt.next, AFTER_SIGN_IN)));
  out.cookies.set(SESSION_COOKIE, res.data.access_token, cookieOptions(res.data.expires_in));
  return out;
}
