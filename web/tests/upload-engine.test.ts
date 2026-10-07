import { describe, expect, it, vi } from "vitest";
import { fingerprint, UploadTask, type TaskState } from "@/lib/upload/engine";

const PART = 5;

/** A fake API: remembers which parts "storage" has, like the real upload endpoints. */
function fakeApi(opts: { size: number; stored?: number[]; resumeId?: string; finalStatus?: string }) {
  const stored = new Map<number, string>((opts.stored ?? []).map((n) => [n, `"etag-${n}"`]));
  const calls: { method: string; path: string; body?: unknown }[] = [];
  const upload = (status = "uploading") => ({
    id: opts.resumeId ?? "u1",
    filename: "clip.mp4",
    size_bytes: opts.size,
    part_size: PART,
    part_count: Math.ceil(opts.size / PART),
    status,
    result: {},
    video_id: status === "uploading" ? null : "v1",
    error: null,
    uploaded_parts: [...stored.entries()].map(([part_number, etag]) => ({ part_number, etag, size: PART })),
  });
  let completed = false;
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    const path = url.replace("/api/v1", "");
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ method, path, body });
    const ok = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status });
    if (method === "POST" && path === "/uploads") return ok(upload(), 201);
    if (method === "POST" && path.endsWith("/parts"))
      return ok({ urls: body.part_numbers.map((n: number) => ({ part_number: n, url: `https://storage/part/${n}` })), expires_in: 3600 });
    if (method === "POST" && path.endsWith("/complete")) {
      completed = true;
      return ok(upload("processing"), 202);
    }
    if (method === "GET") return ok(upload(completed ? (opts.finalStatus ?? "processed") : "uploading"));
    if (method === "DELETE") return new Response(null, { status: 204 });
    return ok({ detail: "unexpected" }, 500);
  }) as unknown as typeof globalThis.fetch;
  const putPart = vi.fn(async (url: string, blob: Blob, onProgress: (n: number) => void, signal?: AbortSignal) => {
    if (signal?.aborted) throw new Error("aborted");
    const n = Number(url.split("/").pop());
    onProgress(blob.size);
    stored.set(n, `"etag-${n}"`);
    return `"etag-${n}"`;
  });
  return { fetch, putPart, calls, stored };
}

function memoryStore() {
  const data = new Map<string, string>();
  return {
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
    removeItem: (k: string) => void data.delete(k),
    data,
  };
}

const file = (size: number) => new File([new Uint8Array(size)], "clip.mp4", { type: "video/mp4", lastModified: 1 });

describe("UploadTask", () => {
  it("uploads every part, completes with sorted ETags, and waits for ingest", async () => {
    const api = fakeApi({ size: 12 });
    const states: TaskState[] = [];
    const progress: number[] = [];
    const task = new UploadTask(file(12), { fetch: api.fetch, putPart: api.putPart, pollMs: 1, store: memoryStore() }, {
      onState: (s) => states.push(s),
      onProgress: (sent) => progress.push(sent),
    });
    await task.start();
    expect(api.putPart).toHaveBeenCalledTimes(3);
    const complete = api.calls.find((c) => c.path.endsWith("/complete"))!;
    expect(complete.body).toEqual({ parts: [1, 2, 3].map((n) => ({ part_number: n, etag: `"etag-${n}"` })) });
    expect(states).toEqual(["uploading", "processing", "processed"]);
    expect(progress.at(-1)).toBe(12);
  });

  it("resumes a remembered upload, sending only the parts storage doesn't have", async () => {
    const api = fakeApi({ size: 12, stored: [1, 3], resumeId: "u-resume" });
    const store = memoryStore();
    const f = file(12);
    store.setItem("egolabs.uploads", JSON.stringify({ [fingerprint(f)]: "u-resume" }));
    const task = new UploadTask(f, { fetch: api.fetch, putPart: api.putPart, pollMs: 1, store });
    await task.start();
    expect(api.calls.some((c) => c.method === "POST" && c.path === "/uploads")).toBe(false);
    expect(api.putPart.mock.calls.map((c) => c[0])).toEqual(["https://storage/part/2"]);
    expect(store.data.size).toBe(0); // forgotten once complete
  });

  it("retries a failed part", async () => {
    const api = fakeApi({ size: 5 });
    let failures = 1;
    const flaky = vi.fn(async (url: string, blob: Blob, onProgress: (n: number) => void, signal: AbortSignal) => {
      if (failures-- > 0) throw new Error("network");
      return api.putPart(url, blob, onProgress, signal);
    });
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const task = new UploadTask(file(5), { fetch: api.fetch, putPart: flaky, pollMs: 1, store: null });
    await task.start();
    vi.useRealTimers();
    expect(flaky).toHaveBeenCalledTimes(2);
    expect(task.state).toBe("processed");
  });

  it("reports failure after three attempts", async () => {
    const api = fakeApi({ size: 5 });
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const errors: (string | undefined)[] = [];
    const task = new UploadTask(file(5), { fetch: api.fetch, putPart: async () => Promise.reject(new Error("storage down")), store: null }, {
      onState: (s, d) => s === "failed" && errors.push(d?.error),
    });
    await task.start();
    vi.useRealTimers();
    expect(errors).toEqual(["storage down"]);
  });

  it("pauses without failing, and cancel aborts the upload on the server", async () => {
    const api = fakeApi({ size: 12 });
    let release: () => void = () => {};
    const slow = vi.fn((_url: string, _blob: Blob, _p: (n: number) => void, signal: AbortSignal) =>
      new Promise<string>((resolve, reject) => {
        release = () => resolve('"x"');
        signal.addEventListener("abort", () => reject(new Error("aborted")));
      }),
    );
    const task = new UploadTask(file(12), { fetch: api.fetch, putPart: slow, store: memoryStore() });
    const running = task.start();
    await vi.waitFor(() => expect(slow).toHaveBeenCalled());
    task.pause();
    await running;
    expect(task.state).toBe("paused");
    await task.cancel();
    expect(task.state).toBe("aborted");
    expect(api.calls.some((c) => c.method === "DELETE" && c.path === "/uploads/u1")).toBe(true);
    release();
  });

  it("surfaces duplicates from the ingest result", async () => {
    const api = fakeApi({ size: 5, finalStatus: "duplicate" });
    const task = new UploadTask(file(5), { fetch: api.fetch, putPart: api.putPart, pollMs: 1, store: null });
    await task.start();
    expect(task.state).toBe("duplicate");
  });
});
