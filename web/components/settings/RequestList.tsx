"use client";

import { Check, X } from "lucide-react";
import { useState, useTransition } from "react";
import { EmptyState } from "@/components/ui";
import type { HeldVideo, WaitingUpload } from "@/lib/api/types";
import { reviewUpload, reviewVideo, type AdminState } from "@/lib/actions/admin";
import { formatBytes, formatDateTime, formatDuration } from "@/lib/format";

interface Item {
  id: string;
  kind: "upload" | "video";
  filename: string;
  detail: string;
  reason: string | null;
  who: string | null;
  createdAt: string;
}

function Row({ item }: { item: Item }) {
  const [pending, start] = useTransition();
  const [result, setResult] = useState<AdminState>();
  const act = (allow: boolean) =>
    start(async () => {
      const reason = allow ? undefined : window.prompt(`Why not? (shown to the uploader, optional)`) ?? undefined;
      setResult(await (item.kind === "upload" ? reviewUpload(item.id, allow, reason) : reviewVideo(item.id, allow, reason)));
    });
  return (
    <li className="flex flex-wrap items-center gap-3 px-4 py-3">
      <div className="min-w-0 flex-1">
        <div className="truncate font-medium">{item.filename}</div>
        <div className="text-xs text-ink-2">
          {item.detail} · {item.who ?? "Unknown"} · {formatDateTime(item.createdAt)}
        </div>
        {item.reason ? <div className="text-xs text-warning">{item.reason}</div> : null}
        {result?.error ? <div className="text-xs text-error">{result.error}</div> : null}
      </div>
      <div className="flex gap-2">
        <button type="button" disabled={pending} onClick={() => act(true)} className="inline-flex h-8 items-center gap-1.5 rounded-md bg-ink px-3 text-xs font-semibold text-ground hover:opacity-90 disabled:opacity-50">
          <Check className="size-3.5" aria-hidden /> {item.kind === "upload" ? "Allow upload" : "Allow processing"}
        </button>
        <button type="button" disabled={pending} onClick={() => act(false)} className="inline-flex h-8 items-center gap-1.5 rounded-md border border-line px-3 text-xs font-semibold hover:bg-hover disabled:opacity-50">
          <X className="size-3.5" aria-hidden /> Reject
        </button>
      </div>
    </li>
  );
}

export function RequestList({ uploads, videos }: { uploads: WaitingUpload[]; videos: HeldVideo[] }) {
  const items: Item[] = [
    ...uploads.map((u) => ({ id: u.id, kind: "upload" as const, filename: u.filename, detail: `Upload of ${formatBytes(u.size_bytes)}`,
      reason: u.reason, who: u.uploaded_by_name || u.uploaded_by_email || null, createdAt: u.created_at })),
    ...videos.map((v) => ({ id: v.id, kind: "video" as const, filename: v.filename, detail: `Video of ${formatDuration(v.duration_s)}`,
      reason: v.reason, who: v.uploaded_by_name || v.uploaded_by_email || null, createdAt: v.created_at })),
  ].sort((a, b) => a.createdAt.localeCompare(b.createdAt));
  if (!items.length)
    return (
      <div className="rounded-lg border border-line">
        <EmptyState size="compact" title="Nothing is waiting for you" description="Uploads over the size limit and videos over the length limit show up here." />
      </div>
    );
  return (
    <ul aria-label="Waiting for you" className="divide-y divide-line rounded-lg border border-line">
      {items.map((item) => <Row key={`${item.kind}-${item.id}`} item={item} />)}
    </ul>
  );
}
