import { NextResponse, type NextRequest } from "next/server";
import { SESSION_COOKIE } from "@/lib/auth/constants";
import { safeNext } from "@/lib/auth/session";

/** The session cookie was missing, expired, or revoked: clear it and go to sign-in. */
export function GET(request: NextRequest) {
  const next = safeNext(request.nextUrl.searchParams.get("next"));
  const login = new URL("/login", request.url);
  if (next !== "/") login.searchParams.set("next", next);
  login.searchParams.set("expired", "1");
  const res = NextResponse.redirect(login);
  res.cookies.delete(SESSION_COOKIE);
  return res;
}
