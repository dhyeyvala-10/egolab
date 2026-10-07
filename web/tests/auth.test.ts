import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { apiFetch } from "@/lib/api/client";
import { PATH_HEADER, SESSION_COOKIE } from "@/lib/auth/constants";
import { safeNext } from "@/lib/auth/session";
import { proxy } from "@/proxy";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("safeNext", () => {
  it("allows same-site paths only", () => {
    expect(safeNext("/data/videos?page=2")).toBe("/data/videos?page=2");
    expect(safeNext("https://evil.example")).toBe("/");
    expect(safeNext("//evil.example")).toBe("/");
    expect(safeNext("/\\evil.example")).toBe("/");
    expect(safeNext(undefined)).toBe("/");
    expect(safeNext(["/a"])).toBe("/");
  });

  it("falls back to the given destination", () => {
    expect(safeNext(null, "/profile")).toBe("/profile");
    expect(safeNext("//evil.example", "/profile")).toBe("/profile");
    expect(safeNext("/cv/hands", "/profile")).toBe("/cv/hands");
  });
});

function stubFetch(status: number, body: unknown) {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("apiFetch", () => {
  it("sends JSON with the bearer token and returns data", async () => {
    const fetchMock = stubFetch(200, { email: "a@example.com" });
    const res = await apiFetch<{ email: string }>("/api/v1/auth/me", { token: "tok" });
    expect(res).toEqual({ ok: true, data: { email: "a@example.com" } });
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/api/v1/auth/me");
    expect((init.headers as Record<string, string>).authorization).toBe("Bearer tok");
    expect(init.cache).toBe("no-store");
  });

  it("uses FastAPI's string detail as the message", async () => {
    stubFetch(409, { detail: "An account with this email already exists" });
    const res = await apiFetch("/api/v1/auth/register", { method: "POST", body: {} });
    expect(res).toMatchObject({ ok: false, kind: "http", status: 409, message: "An account with this email already exists" });
  });

  it("summarises validation errors with the field name", async () => {
    stubFetch(422, { detail: [{ loc: ["body", "password"], msg: "String should have at least 8 characters" }] });
    const res = await apiFetch("/api/v1/auth/register", { method: "POST", body: {} });
    expect(res).toMatchObject({ ok: false, message: "password: String should have at least 8 characters" });
  });

  it("reports an unreachable API instead of throwing", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("fetch failed"))));
    const res = await apiFetch("/api/v1/health");
    expect(res).toEqual({ ok: false, kind: "unreachable", message: "fetch failed" });
  });
});

describe("proxy", () => {
  it("sends visitors without a session to sign-in, keeping the destination", () => {
    const res = proxy(new NextRequest("http://localhost:3000/data/sessions?page=2"));
    expect(res.status).toBe(307);
    const location = new URL(res.headers.get("location")!);
    expect(location.pathname).toBe("/login");
    expect(location.searchParams.get("next")).toBe("/data/sessions?page=2");
  });

  it("lets anyone see the landing page", () => {
    const res = proxy(new NextRequest("http://localhost:3000/"));
    expect(res.headers.get("location")).toBeNull();
    expect(res.headers.get(`x-middleware-request-${PATH_HEADER}`)).toBe("/");
  });

  it("lets requests with a session cookie through and records the path", () => {
    const req = new NextRequest("http://localhost:3000/cv/hands", { headers: { cookie: `${SESSION_COOKIE}=abc` } });
    const res = proxy(req);
    expect(res.headers.get("location")).toBeNull();
    expect(res.headers.get(`x-middleware-request-${PATH_HEADER}`)).toBe("/cv/hands");
  });
});
