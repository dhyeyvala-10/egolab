/**
 * Resumable browser → object storage upload (S3 multipart via presigned part URLs).
 *
 * The API tracks the multipart upload; storage keeps the parts. After a pause, a network drop, or a
 * page reload, re-adding the same file resumes: the task asks the API which parts storage already has
 * and sends only the rest.
 */
import type { UploadDetail, UploadRead } from "@/lib/api/types";

export type TaskState =
  | "queued"
  | "waiting" // over the admin's size limit: nothing is sent until they allow it
  | "uploading"
  | "paused"
  | "processing"
  | "processed"
  | "duplicate"
  | "failed"
  | "aborted";

export interface TaskOptions {
  sessionId?: string | null;
  sequenceFps?: number | null;
  concurrency?: number;
  /** Where resumable upload ids are remembered between page loads. */
  store?: Pick<Storage, "getItem" | "setItem" | "removeItem"> | null;
  /** Send one part; resolves to its ETag. Injectable for tests. */
  putPart?: (url: string, body: Blob, onProgress: (sent: number) => void, signal: AbortSignal) => Promise<string>;
  fetch?: typeof fetch;
  pollMs?: number;
  /** How often to ask whether the admin has allowed an upload that waits for them. */
  approvalPollMs?: number;
}

export interface TaskEvents {
  onState?: (state: TaskState, detail?: { error?: string; upload?: UploadRead }) => void;
  onProgress?: (sentBytes: number, totalBytes: number) => void;
}

class Stopped extends Error {}

const STORE_KEY = "egolabs.uploads";
const API = "/api/v1";

export function fingerprint(file: File): string {
  return `${file.name}:${file.size}:${file.lastModified}`;
}

function readStore(store: TaskOptions["store"]): Record<string, string> {
  try {
    return JSON.parse(store?.getItem(STORE_KEY) ?? "{}") as Record<string, string>;
  } catch {
    return {};
  }
}

function writeStore(store: TaskOptions["store"], map: Record<string, string>) {
  try {
    if (Object.keys(map).length) store?.setItem(STORE_KEY, JSON.stringify(map));
    else store?.removeItem(STORE_KEY);
  } catch {
    /* storage unavailable: uploads still work, they just can't resume after a reload */
  }
}

export function xhrPutPart(url: string, body: Blob, onProgress: (sent: number) => void, signal: AbortSignal): Promise<string> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    xhr.upload.onprogress = (e) => onProgress(e.loaded);
    xhr.onload = () => {
      if (xhr.status < 200 || xhr.status >= 300) return reject(new Error(`Storage returned ${xhr.status}`));
      const etag = xhr.getResponseHeader("ETag");
      if (!etag) return reject(new Error("Storage didn't return an ETag (check its CORS settings expose ETag)"));
      resolve(etag);
    };
    xhr.onerror = () => reject(new Error("Network error while sending a part"));
    xhr.onabort = () => reject(new Stopped("aborted"));
    signal.addEventListener("abort", () => xhr.abort(), { once: true });
    xhr.send(body);
  });
}

async function json<T>(res: Response): Promise<T> {
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = (body as { detail?: unknown }).detail;
    throw new Error(typeof detail === "string" ? detail : `Request failed (${res.status})`);
  }
  return body as T;
}

export class UploadTask {
  readonly file: File;
  uploadId: string | null = null;
  state: TaskState = "queued";
  private controller: AbortController | null = null;
  private readonly opts: Required<Omit<TaskOptions, "sessionId" | "sequenceFps" | "store">> & Pick<TaskOptions, "sessionId" | "sequenceFps" | "store">;

  constructor(file: File, options: TaskOptions = {}, private readonly events: TaskEvents = {}) {
    this.file = file;
    this.opts = {
      concurrency: 3,
      putPart: xhrPutPart,
      fetch: (...args) => fetch(...args),
      pollMs: 2000,
      approvalPollMs: 5000,
      ...options,
    };
  }

  private set(state: TaskState, detail?: { error?: string; upload?: UploadRead }) {
    this.state = state;
    this.events.onState?.(state, detail);
  }

  private request<T>(path: string, init?: RequestInit): Promise<T> {
    return this.opts.fetch(`${API}${path}`, {
      ...init,
      headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
    }).then((res) => json<T>(res));
  }

  /** Reuse a remembered, still-open upload for this exact file, else create one. */
  private async open(): Promise<UploadDetail> {
    const key = fingerprint(this.file);
    const remembered = this.uploadId ?? readStore(this.opts.store)[key];
    if (remembered) {
      try {
        const existing = await this.request<UploadDetail>(`/uploads/${remembered}`);
        if (existing.status === "uploading" || existing.status === "awaiting_approval") return existing;
      } catch {
        /* gone or not ours: start over */
      }
    }
    const created = await this.request<UploadDetail>("/uploads", {
      method: "POST",
      body: JSON.stringify({
        filename: this.file.name,
        size_bytes: this.file.size,
        content_type: this.file.type || null,
        session_id: this.opts.sessionId || null,
        sequence_fps: this.opts.sequenceFps || null,
      }),
    });
    writeStore(this.opts.store, { ...readStore(this.opts.store), [key]: created.id });
    return { ...created, uploaded_parts: [] };
  }

  async start(): Promise<void> {
    if (this.state === "uploading" || this.state === "processing" || this.state === "waiting") return;
    this.controller = new AbortController();
    const signal = this.controller.signal;
    try {
      this.set("uploading");
      let upload = await this.open();
      this.uploadId = upload.id;
      if (upload.status === "awaiting_approval") {
        upload = await this.awaitApproval(upload, signal);
        this.set("uploading");
      }
      const done = new Map<number, string>((upload.uploaded_parts ?? []).map((p) => [p.part_number, p.etag]));
      const size = upload.part_size;
      const partBytes = (n: number) => Math.min(size, this.file.size - (n - 1) * size);
      const inFlight = new Map<number, number>();
      let confirmed = [...done.keys()].reduce((sum, n) => sum + partBytes(n), 0);
      const report = () => this.events.onProgress?.(confirmed + [...inFlight.values()].reduce((a, b) => a + b, 0), this.file.size);
      report();

      const pending = Array.from({ length: upload.part_count }, (_, i) => i + 1).filter((n) => !done.has(n));
      const urls = new Map<number, string>();
      const sign = async (n: number) => {
        if (!urls.has(n)) {
          const batch = pending.filter((p) => !urls.has(p) && p >= n).slice(0, 20);
          const res = await this.request<{ urls: { part_number: number; url: string }[] }>(`/uploads/${upload.id}/parts`, {
            method: "POST",
            body: JSON.stringify({ part_numbers: batch }),
            signal,
          });
          for (const u of res.urls) urls.set(u.part_number, u.url);
        }
        return urls.get(n)!;
      };

      const queue = [...pending];
      const worker = async () => {
        for (let n = queue.shift(); n !== undefined; n = queue.shift()) {
          const blob = this.file.slice((n - 1) * size, (n - 1) * size + partBytes(n));
          for (let attempt = 1; ; attempt++) {
            if (signal.aborted) throw new Stopped("paused");
            try {
              const url = await sign(n);
              const etag = await this.opts.putPart(url, blob, (sent) => { inFlight.set(n, sent); report(); }, signal);
              done.set(n, etag);
              inFlight.delete(n);
              confirmed += partBytes(n);
              report();
              break;
            } catch (err) {
              inFlight.delete(n);
              if (err instanceof Stopped || signal.aborted) throw new Stopped("paused");
              if (attempt >= 3) throw err;
              urls.delete(n); // the URL may have expired
              await new Promise((r) => setTimeout(r, 500 * 2 ** attempt));
            }
          }
        }
      };
      await Promise.all(Array.from({ length: Math.min(this.opts.concurrency, Math.max(1, pending.length)) }, worker));

      const completed = await this.request<UploadRead>(`/uploads/${upload.id}/complete`, {
        method: "POST",
        body: JSON.stringify({ parts: [...done.entries()].sort((a, b) => a[0] - b[0]).map(([part_number, etag]) => ({ part_number, etag })) }),
        signal,
      });
      const store = readStore(this.opts.store);
      delete store[fingerprint(this.file)];
      writeStore(this.opts.store, store);
      this.set("processing", { upload: completed });
      await this.poll(upload.id, signal);
    } catch (err) {
      if (err instanceof Stopped || signal.aborted) {
        if (this.state !== "aborted") this.set("paused");
        return;
      }
      this.set("failed", { error: err instanceof Error ? err.message : String(err) });
    }
  }

  /** Wait until the admin allows (then carry on) or rejects the upload. */
  private async awaitApproval(upload: UploadDetail, signal: AbortSignal): Promise<UploadDetail> {
    this.set("waiting", { upload });
    for (;;) {
      await new Promise((r) => setTimeout(r, this.opts.approvalPollMs));
      if (signal.aborted) throw new Stopped("stopped");
      const now = await this.request<UploadDetail>(`/uploads/${upload.id}`);
      if (now.status === "uploading") return now;
      if (now.status !== "awaiting_approval") {
        const store = readStore(this.opts.store);
        delete store[fingerprint(this.file)];
        writeStore(this.opts.store, store);
        throw new Error(now.status === "rejected" ? `Rejected by the admin: ${now.error ?? "no reason given"}` : `Upload ${now.status}`);
      }
    }
  }

  private async poll(id: string, signal: AbortSignal) {
    for (;;) {
      await new Promise((r) => setTimeout(r, this.opts.pollMs));
      if (signal.aborted) throw new Stopped("stopped");
      const upload = await this.request<UploadRead>(`/uploads/${id}`);
      if (upload.status !== "processing") {
        this.set(upload.status === "failed" ? "failed" : (upload.status as TaskState), { upload, error: upload.error ?? undefined });
        return;
      }
    }
  }

  pause() {
    if (this.state === "uploading" || this.state === "waiting") this.controller?.abort();
  }

  async cancel() {
    const previous = this.state;
    this.state = "aborted"; // before aborting, so the interrupted start() doesn't report "paused"
    this.controller?.abort();
    if (this.uploadId && (previous === "uploading" || previous === "paused" || previous === "queued" || previous === "waiting")) {
      await this.opts.fetch(`${API}/uploads/${this.uploadId}`, { method: "DELETE" }).catch(() => undefined);
      const store = readStore(this.opts.store);
      delete store[fingerprint(this.file)];
      writeStore(this.opts.store, store);
    }
    this.set("aborted");
  }
}
