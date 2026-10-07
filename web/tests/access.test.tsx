import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Progress, sinceText, STALLED_MS } from "@/components/data/RecentUploads";
import { describeAgent } from "@/components/settings/ActivityTables";
import { isOnline } from "@/components/settings/UserTable";
import type { UploadRead, UserRead } from "@/lib/api/types";
import { UploadTask, type TaskState } from "@/lib/upload/engine";

vi.mock("@/lib/actions/admin", () => ({ cancelUpload: vi.fn(), setRole: vi.fn(), setActive: vi.fn() }));

describe("an upload over the admin's limit", () => {
  /** The API answers "awaiting_approval" twice, then the admin's decision. */
  function api(decision: "uploading" | "rejected") {
    let checks = 0;
    let completed = false;
    const base = { id: "u1", filename: "big.mp4", size_bytes: 10, part_size: 10, part_count: 1, result: {}, video_id: null,
      approval_reason: "10 B is over the 5 B upload limit", uploaded_parts: [] };
    const fetch = vi.fn(async (url: string, init?: RequestInit) => {
      const path = url.replace("/api/v1", "");
      const method = init?.method ?? "GET";
      const ok = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status });
      if (method === "POST" && path === "/uploads") return ok({ ...base, status: "awaiting_approval", error: null }, 201);
      if (method === "GET" && path === "/uploads/u1") {
        if (completed) return ok({ ...base, status: "processed", error: null });
        checks += 1;
        if (checks < 3) return ok({ ...base, status: "awaiting_approval", error: null });
        return ok({ ...base, status: decision, error: decision === "rejected" ? "Too big for now" : null });
      }
      if (method === "POST" && path.endsWith("/parts")) return ok({ urls: [{ part_number: 1, url: "https://s/1" }], expires_in: 60 });
      if (method === "POST" && path.endsWith("/complete")) {
        completed = true;
        return ok({ ...base, status: "processing" }, 202);
      }
      return ok({ detail: "unexpected" }, 500);
    }) as unknown as typeof globalThis.fetch;
    return fetch;
  }
  const file = new File([new Uint8Array(10)], "big.mp4", { lastModified: 1 });

  it("waits, sending nothing, and carries on by itself once allowed", async () => {
    const putPart = vi.fn(async () => '"e1"');
    const states: TaskState[] = [];
    const task = new UploadTask(file, { fetch: api("uploading"), putPart, pollMs: 1, approvalPollMs: 1 }, { onState: (s) => states.push(s) });
    await task.start();
    expect(states.slice(0, 3)).toEqual(["uploading", "waiting", "uploading"]);
    expect(states.at(-1)).toBe("processed");
    expect(putPart).toHaveBeenCalledTimes(1);
  });

  it("fails with the admin's reason when rejected", async () => {
    const putPart = vi.fn(async () => '"e1"');
    const events: { state: TaskState; error?: string }[] = [];
    const task = new UploadTask(file, { fetch: api("rejected"), putPart, approvalPollMs: 1 }, {
      onState: (state, d) => events.push({ state, error: d?.error }),
    });
    await task.start();
    expect(events.at(-1)).toEqual({ state: "failed", error: "Rejected by the admin: Too big for now" });
    expect(putPart).not.toHaveBeenCalled();
  });
});

describe("upload progress", () => {
  const now = Date.parse("2026-09-25T12:00:00Z");
  const upload = (over: Partial<UploadRead>) =>
    ({ id: "u", filename: "a.mp4", size_bytes: 1000, status: "uploading", created_at: "2026-09-25T11:59:00Z",
      received_bytes: 250, last_data_at: "2026-09-25T11:59:55Z", ...over }) as UploadRead;

  it("says how much arrived and when the last piece did", () => {
    render(<Progress upload={upload({})} now={now} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "25");
    expect(screen.getByText(/\(25%\) · last data 5 s ago/)).toBeInTheDocument();
  });

  it("calls an upload that stopped moving paused", () => {
    const old = new Date(now - STALLED_MS - 60_000).toISOString();
    render(<Progress upload={upload({ last_data_at: old })} now={now} />);
    expect(screen.getByText(/paused, last data 3 min ago/)).toBeInTheDocument();
    expect(sinceText(null, now)).toBe("nothing received yet");
  });
});

describe("the admin's pages", () => {
  it("knows who is online and names browsers", () => {
    const now = Date.parse("2026-09-25T12:00:00Z");
    const user = (seen: string | null) => ({ last_seen_at: seen }) as UserRead;
    expect(isOnline(user("2026-09-25T11:58:00Z"), now)).toBe(true);
    expect(isOnline(user("2026-09-25T11:00:00Z"), now)).toBe(false);
    expect(isOnline(user(null), now)).toBe(false);
    const chrome = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36";
    expect(describeAgent(chrome)).toBe("Chrome on Windows");
    expect(describeAgent("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile Safari/604.1")).toBe("Safari on iOS");
    expect(describeAgent(null)).toBe("Unknown");
  });
});
