"use client";

import { FileUp, Pause, Play, RotateCcw, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type DragEvent } from "react";
import { StatusBadge } from "@/components/ui";
import type { Ref, UploadRead } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { formatBytes } from "@/lib/format";
import { UploadTask, type TaskState } from "@/lib/upload/engine";
import { inputClass } from "./Field";

const ACCEPT = [".mp4", ".mov", ".avi", ".mkv", ".zip", ".json", ".csv"];
const MAX_PARALLEL_FILES = 2;

interface Item {
  id: string;
  name: string;
  size: number;
  state: TaskState;
  sent: number;
  error?: string;
  upload?: UploadRead;
}

function safeStorage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function resultText(item: Item): React.ReactNode {
  const r = item.upload?.result as { created?: string[]; duplicates?: unknown[]; corrupt?: string[]; sidecars?: string[]; skipped?: string[] } | undefined;
  if (item.state === "duplicate" && item.upload?.video_id)
    return (
      <>
        Already in the library —{" "}
        <Link href={`/data/videos/${item.upload.video_id}`} className="font-medium text-ink underline">
          view the existing video
        </Link>
      </>
    );
  if (item.state === "processed" && r) {
    const parts = [
      r.created?.length ? `${r.created.length} video${r.created.length === 1 ? "" : "s"} added` : null,
      r.duplicates?.length ? `${r.duplicates.length} duplicate${r.duplicates.length === 1 ? "" : "s"} linked` : null,
      r.corrupt?.length ? `${r.corrupt.length} unreadable (flagged)` : null,
      r.sidecars?.length ? `${r.sidecars.length} sidecar${r.sidecars.length === 1 ? "" : "s"}` : null,
      r.skipped?.length ? `${r.skipped.length} skipped` : null,
    ].filter(Boolean);
    const single = item.upload?.video_id && (r.created?.length ?? 0) + (r.corrupt?.length ?? 0) === 1;
    return (
      <>
        {parts.join(", ") || "Nothing to ingest"}
        {single ? (
          <>
            {" — "}
            <Link href={`/data/videos/${item.upload!.video_id}`} className="font-medium text-ink underline">
              view
            </Link>
          </>
        ) : null}
      </>
    );
  }
  if (item.state === "processing") return "Checksum, probe, and preview generation…";
  if (item.state === "waiting")
    return `Waiting for the admin to allow it (${item.upload?.approval_reason ?? "over the size limit"}). Keep this page open and it starts by itself, or add the same file again later.`;
  if (item.state === "paused") return "Paused — resume any time, even after reloading this page";
  return item.error;
}

export function Uploader({ sessions, defaultSessionId, sizeLimit = null }: { sessions: Ref[]; defaultSessionId?: string; sizeLimit?: number | null }) {
  const router = useRouter();
  const [items, setItems] = useState<Item[]>([]);
  const [sessionId, setSessionId] = useState(defaultSessionId ?? "");
  const [fps, setFps] = useState("");
  const [dragging, setDragging] = useState(false);
  const [tasks] = useState(() => new Map<string, UploadTask>());
  const input = useRef<HTMLInputElement>(null);

  const update = useCallback((id: string, patch: Partial<Item>) => {
    setItems((all) => all.map((it) => (it.id === id ? { ...it, ...patch } : it)));
  }, []);

  // Start queued files, a few at a time.
  useEffect(() => {
    const running = items.filter((i) => i.state === "uploading" || i.state === "waiting").length;
    const next = items.filter((i) => i.state === "queued").slice(0, Math.max(0, MAX_PARALLEL_FILES - running));
    for (const item of next) void tasks.get(item.id)?.start();
  }, [items, tasks]);

  // Warn before leaving mid-upload (parts sent so far are kept and can be resumed).
  useEffect(() => {
    const busy = items.some((i) => i.state === "uploading");
    if (!busy) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [items]);

  const add = (files: FileList | File[]) => {
    const accepted: Item[] = [];
    const rejected: Item[] = [];
    for (const file of Array.from(files)) {
      const id = crypto.randomUUID();
      const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
      if (!ACCEPT.includes(ext)) {
        rejected.push({ id, name: file.name, size: file.size, state: "failed", sent: 0, error: `Unsupported type. Upload ${ACCEPT.join(", ")}` });
        continue;
      }
      const task = new UploadTask(
        file,
        { sessionId: sessionId || null, sequenceFps: fps ? Number(fps) : null, store: safeStorage() },
        {
          onState: (state, detail) => {
            update(id, { state, error: detail?.error, ...(detail?.upload ? { upload: detail.upload } : {}) });
            if (state === "processed" || state === "duplicate" || state === "failed") router.refresh();
          },
          onProgress: (sent) => update(id, { sent }),
        },
      );
      tasks.set(id, task);
      accepted.push({ id, name: file.name, size: file.size, state: "queued", sent: 0 });
    }
    setItems((all) => [...accepted, ...rejected, ...all]);
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    if (e.dataTransfer.files.length) add(e.dataTransfer.files);
  };

  const activeCount = items.filter((i) => ["queued", "waiting", "uploading", "processing"].includes(i.state)).length;

  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_200px]">
        <div className="flex min-w-0 flex-col gap-1">
          <label htmlFor="upload-session" className="text-xs font-semibold">Session</label>
          <select id="upload-session" className={inputClass} value={sessionId} onChange={(e) => setSessionId(e.target.value)}>
            <option value="">No session (assign later)</option>
            {sessions.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
          <span className="text-xs text-ink-3">
            Applies to files added from now on. <Link href="/data/sessions/new" className="underline">Create a session</Link>
          </span>
        </div>
        <div className="flex min-w-0 flex-col gap-1">
          <label htmlFor="upload-fps" className="text-xs font-semibold">Image sequence FPS</label>
          <input id="upload-fps" className={inputClass} type="number" min="0.1" step="any" inputMode="decimal" placeholder="Unknown" value={fps} onChange={(e) => setFps(e.target.value)} />
          <span className="text-xs text-ink-3">For folders of frames inside a ZIP</span>
        </div>
      </div>

      <div
        role="button"
        tabIndex={0}
        aria-label="Add files to upload"
        onClick={() => input.current?.click()}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border border-dashed px-6 py-10 text-center transition-colors",
          dragging ? "border-ink bg-hover" : "border-line-strong bg-subtle hover:bg-hover",
        )}
      >
        <FileUp className="size-6 text-ink-2" aria-hidden />
        <div className="font-semibold">Drop videos here, or click to choose</div>
        <div className="max-w-[60ch] text-ink-2">
          MP4, MOV, AVI, MKV; ZIP archives of videos, image-sequence folders, and sidecars; JSON/CSV metadata sidecars.
          Files go straight to storage in resumable parts.
        </div>
        {sizeLimit ? <div className="text-xs text-ink-3">Files over {formatBytes(sizeLimit)} wait for the admin to allow them.</div> : null}
        <input ref={input} type="file" multiple accept={ACCEPT.join(",")} className="hidden" onChange={(e) => e.target.files && (add(e.target.files), (e.target.value = ""))} />
      </div>

      {items.length > 0 ? (
        <section aria-label="Upload queue" className="rounded-lg border border-line">
          <div className="flex items-center justify-between border-b border-line px-3.5 py-2 text-xs text-ink-2">
            <span>{activeCount ? `${activeCount} in progress` : "All done"}</span>
            <button type="button" className="hover:text-ink" onClick={() => setItems((all) => all.filter((i) => ["queued", "waiting", "uploading", "processing", "paused"].includes(i.state)))}>
              Clear finished
            </button>
          </div>
          <ul className="divide-y divide-line">
            {items.map((item) => {
              const task = tasks.get(item.id);
              const pct = item.size ? Math.min(100, Math.round((item.sent / item.size) * 100)) : 100;
              return (
                <li key={item.id} className="flex flex-col gap-1.5 px-3.5 py-2.5" data-state={item.state}>
                  <div className="flex items-center gap-2">
                    <span className="min-w-0 flex-1 truncate font-medium">{item.name}</span>
                    <span className="text-xs tabular-nums text-ink-3">{formatBytes(item.size)}</span>
                    <StatusBadge
                      status={item.state === "processed" ? "ready" : item.state === "waiting" ? "awaiting_approval" : item.state}
                      label={item.state === "processed" ? "Done" : item.state === "waiting" ? "Waiting for admin" : undefined}
                    />
                    {item.state === "uploading" ? (
                      <button type="button" aria-label={`Pause ${item.name}`} onClick={() => task?.pause()} className="grid size-7 place-items-center rounded-md hover:bg-hover">
                        <Pause className="size-3.5" aria-hidden />
                      </button>
                    ) : null}
                    {item.state === "paused" || (item.state === "failed" && task) ? (
                      <button type="button" aria-label={`${item.state === "paused" ? "Resume" : "Retry"} ${item.name}`} onClick={() => void task?.start()} className="grid size-7 place-items-center rounded-md hover:bg-hover">
                        {item.state === "paused" ? <Play className="size-3.5" aria-hidden /> : <RotateCcw className="size-3.5" aria-hidden />}
                      </button>
                    ) : null}
                    {["queued", "waiting", "uploading", "paused"].includes(item.state) && task ? (
                      <button type="button" aria-label={`Cancel ${item.name}`} onClick={() => void task.cancel()} className="grid size-7 place-items-center rounded-md hover:bg-hover">
                        <X className="size-3.5" aria-hidden />
                      </button>
                    ) : null}
                  </div>
                  {["uploading", "paused", "queued"].includes(item.state) ? (
                    <div className="flex items-center gap-2">
                      <div className="h-1 flex-1 overflow-hidden rounded bg-hover" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label={`${item.name} upload progress`}>
                        <div className={cn("h-full rounded", item.state === "paused" ? "bg-ink-3" : "bg-running")} style={{ width: `${pct}%` }} />
                      </div>
                      <span className="w-20 text-right text-xs tabular-nums text-ink-2">{formatBytes(item.sent)}</span>
                    </div>
                  ) : null}
                  {resultText(item) ? <div className={cn("text-xs", item.state === "failed" ? "text-error" : "text-ink-2")}>{resultText(item)}</div> : null}
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
