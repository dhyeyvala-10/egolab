import { createHash } from "node:crypto";
import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { GET as callback } from "@/app/auth/google/callback/route";
import { GET as start } from "@/app/auth/google/route";
import { SESSION_COOKIE } from "@/lib/auth/constants";
import { challengeFor, GOOGLE_COOKIE, readAttempt, signInError } from "@/lib/auth/google";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

/** Answers the web app's calls to the API: GET /auth/google (config) and POST /auth/google (sign-in). */
function stubApi(signIn: Response = json(200, { access_token: "tok-123", token_type: "bearer", expires_in: 3600, user: {} })) {
  const calls: { url: string; body?: unknown }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    if (init?.method === "POST") return signIn;
    return json(200, { enabled: true, client_id: "cid.apps.googleusercontent.com", authorize_url: "https://accounts.google.com/o/oauth2/v2/auth" });
  }));
  return calls;
}

function cookieValue(res: Response, name: string): string | undefined {
  const line = res.headers.getSetCookie().find((c) => c.startsWith(`${name}=`));
  return line === undefined ? undefined : decodeURIComponent(line.slice(name.length + 1).split(";")[0]);
}

describe("Google sign-in helpers", () => {
  it("makes the S256 PKCE challenge", async () => {
    const verifier = "a-verifier-that-is-at-least-forty-three-characters-long";
    expect(await challengeFor(verifier)).toBe(createHash("sha256").update(verifier).digest("base64url"));
  });

  it("reads only well-formed attempts and known error keys", () => {
    expect(readAttempt(JSON.stringify({ state: "s", verifier: "v", next: "/cv/hands" }))).toEqual({ state: "s", verifier: "v", next: "/cv/hands" });
    expect(readAttempt("not json")).toBeNull();
    expect(readAttempt(JSON.stringify({ state: "s" }))).toBeNull();
    expect(signInError("cancelled")).toMatch(/cancelled/);
    expect(signInError("<script>")).toBeUndefined();
  });
});

describe("/auth/google", () => {
  it("sends the browser to Google with the state and PKCE challenge it keeps in a cookie", async () => {
    stubApi();
    const res = await start(new NextRequest("http://localhost:3000/auth/google?next=%2Fpipelines%2Fruns"));
    expect(res.status).toBe(307);
    const google = new URL(res.headers.get("location")!);
    expect(google.origin + google.pathname).toBe("https://accounts.google.com/o/oauth2/v2/auth");
    const q = Object.fromEntries(google.searchParams);
    expect(q).toMatchObject({
      client_id: "cid.apps.googleusercontent.com",
      redirect_uri: "http://localhost:3000/auth/google/callback",
      response_type: "code",
      scope: "openid email profile",
      code_challenge_method: "S256",
    });
    const attempt = readAttempt(cookieValue(res, GOOGLE_COOKIE))!;
    expect(attempt.next).toBe("/pipelines/runs");
    expect(q.state).toBe(attempt.state);
    expect(q.code_challenge).toBe(await challengeFor(attempt.verifier));
    expect(res.headers.getSetCookie().find((c) => c.startsWith(GOOGLE_COOKIE))).toMatch(/HttpOnly/i);
  });

  it("comes back to the host the browser used, which the sign-in cookie belongs to", async () => {
    stubApi();
    const req = new NextRequest("http://localhost:3100/auth/google", { headers: { host: "127.0.0.1:3100" } });
    const res = await start(req);
    expect(new URL(res.headers.get("location")!).searchParams.get("redirect_uri")).toBe("http://127.0.0.1:3100/auth/google/callback");
    const proxied = new NextRequest("http://10.0.0.5:3000/auth/google", {
      headers: { host: "10.0.0.5:3000", "x-forwarded-host": "ego.example.com", "x-forwarded-proto": "https" },
    });
    expect(new URL((await start(proxied)).headers.get("location")!).searchParams.get("redirect_uri")).toBe("https://ego.example.com/auth/google/callback");
  });

  it("uses PUBLIC_WEB_URL for the callback when set, and says when Google isn't set up", async () => {
    vi.stubEnv("PUBLIC_WEB_URL", "https://ego.example.com/");
    stubApi();
    const res = await start(new NextRequest("http://10.0.0.5:3000/auth/google"));
    expect(new URL(res.headers.get("location")!).searchParams.get("redirect_uri")).toBe("https://ego.example.com/auth/google/callback");

    vi.stubGlobal("fetch", vi.fn(async () => json(200, { enabled: false, client_id: null, authorize_url: "x" })));
    const off = await start(new NextRequest("http://localhost:3000/auth/google"));
    expect(off.headers.get("location")).toBe("https://ego.example.com/login?error=not_configured");
  });
});

describe("/auth/google/callback", () => {
  const attempt = { state: "st4te", verifier: "v".repeat(64), next: "" };
  const back = (query: string, cookie: object | null = attempt) =>
    new NextRequest(`http://localhost:3000/auth/google/callback?${query}`, {
      headers: cookie ? { cookie: `${GOOGLE_COOKIE}=${encodeURIComponent(JSON.stringify(cookie))}` } : {},
    });

  it("signs in through the API, sets the session, and lands on the dashboard", async () => {
    const calls = stubApi();
    const res = await callback(back("code=abc&state=st4te"));
    expect(res.headers.get("location")).toBe("http://localhost:3000/dashboard");
    expect(cookieValue(res, SESSION_COOKIE)).toBe("tok-123");
    expect(cookieValue(res, GOOGLE_COOKIE)).toBe(""); // the attempt is used up
    expect(calls.find((c) => c.body)?.body).toEqual({
      code: "abc", redirect_uri: "http://localhost:3000/auth/google/callback", code_verifier: attempt.verifier,
    });
  });

  it("returns to the page that asked for sign-in", async () => {
    stubApi();
    const res = await callback(back("code=abc&state=st4te", { ...attempt, next: "/datasets/versions" }));
    expect(res.headers.get("location")).toBe("http://localhost:3000/datasets/versions");
  });

  it("refuses a mismatched or missing state without calling the API", async () => {
    const calls = stubApi();
    for (const req of [back("code=abc&state=other"), back("code=abc&state=st4te", null)]) {
      const res = await callback(req);
      expect(res.headers.get("location")).toBe("http://localhost:3000/login?error=expired");
      expect(cookieValue(res, SESSION_COOKIE)).toBeUndefined();
    }
    expect(calls).toHaveLength(0);
  });

  it("explains cancelled and refused sign-ins", async () => {
    stubApi();
    expect((await callback(back("error=access_denied&state=st4te"))).headers.get("location")).toBe("http://localhost:3000/login?error=cancelled");
    stubApi(json(403, { detail: "Account is deactivated" }));
    expect((await callback(back("code=abc&state=st4te"))).headers.get("location")).toBe("http://localhost:3000/login?error=deactivated");
    stubApi(json(400, { detail: "Your Google account's email address isn't verified." }));
    expect((await callback(back("code=abc&state=st4te"))).headers.get("location")).toBe("http://localhost:3000/login?error=unverified");
  });
});
