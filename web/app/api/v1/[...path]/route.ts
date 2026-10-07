import { cookies } from "next/headers";
import { NextResponse, type NextRequest } from "next/server";
import { apiUrl } from "@/lib/api/client";
import { SESSION_COOKIE } from "@/lib/auth/constants";

/**
 * Same-origin gateway to the API for client components (e.g. the uploader). The session token stays in
 * its httpOnly cookie and is added here as a bearer token; the browser never sees it.
 */
async function forward(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!token) return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });

  const { path } = await params;
  const target = `${apiUrl()}/api/v1/${path.map(encodeURIComponent).join("/")}${request.nextUrl.search}`;
  const headers: Record<string, string> = { authorization: `Bearer ${token}`, accept: "application/json" };
  const type = request.headers.get("content-type");
  if (type) headers["content-type"] = type;

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers,
      body: request.method === "GET" || request.method === "HEAD" ? undefined : await request.text(),
      cache: "no-store",
      signal: AbortSignal.timeout(30_000),
    });
  } catch {
    return NextResponse.json({ detail: `Can't reach the Ego Labs API at ${apiUrl()}` }, { status: 502 });
  }
  if (upstream.status === 204) return new NextResponse(null, { status: 204 });
  const out: Record<string, string> = { "content-type": upstream.headers.get("content-type") ?? "application/json" };
  const disposition = upstream.headers.get("content-disposition"); // e.g. a run's logs.txt download
  if (disposition) out["content-disposition"] = disposition;
  return new NextResponse(await upstream.text(), { status: upstream.status, headers: out });
}

export { forward as DELETE, forward as GET, forward as PATCH, forward as POST, forward as PUT };
