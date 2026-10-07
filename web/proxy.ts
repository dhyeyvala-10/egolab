import { NextResponse, type NextRequest } from "next/server";
import { PATH_HEADER, SESSION_COOKIE } from "@/lib/auth/constants";

/**
 * Send visitors without a session cookie to sign-in before rendering any app page. The landing page at
 * `/` is public. The cookie is only a hint: the app layout still validates it with the API on every
 * request.
 */
export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  if (!request.cookies.has(SESSION_COOKIE) && pathname !== "/") {
    const login = new URL("/login", request.url);
    login.searchParams.set("next", `${pathname}${search}`);
    return NextResponse.redirect(login);
  }
  const headers = new Headers(request.headers);
  headers.set(PATH_HEADER, `${pathname}${search}`);
  return NextResponse.next({ request: { headers } });
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|login|register|auth/|api/).*)"],
};
