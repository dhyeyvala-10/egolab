"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Refresher } from "@/components/datasets/Refresher";
import { StatusBadge } from "@/components/ui";
import { browserApi } from "@/lib/api/browser";
import type { AnnotatedVideoRead } from "@/lib/api/types";
import { formatBytes, formatDateTime } from "@/lib/format";
import { DownloadAnnotated } from "./DownloadAnnotated";

const TONE = { building: "running", ready: "succeeded", failed: "failed" } as const;

/**
 * The video with its hand skeletons, object boxes, and movement events drawn on: every render, to
 * download, and a button to render one now from the video's latest runs.
 */
export function AnnotatedVideos({ videoId, items, canEdit, hasRuns }: {
  videoId: string;
  items: AnnotatedVideoRead[];
  canEdit: boolean;
  hasRuns: boolean;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [codec, setCodec] = useState<"h264" | "vp9">("h264");
  const [error, setError] = useState<string | null>(null);
  const [playing, setPlaying] = useState<{ id: string; url: string } | null>(null);
  const watch = async (id: string) => {
    if (playing?.id === id) return setPlaying(null);
    const res = await browserApi<{ url: string }>(`/annotated-videos/${id}/download`, { query: { inline: true } });
    if (res.ok) setPlaying({ id, url: res.data.url });
    else setError(res.message);
  };
  const render = async () => {
    setBusy(true);
    setError(null);
    const res = await browserApi<AnnotatedVideoRead>(`/videos/${videoId}/annotated`, { method: "POST", body: { codec } });
    setBusy(false);
    if (!res.ok) setError(res.message);
    router.refresh();
  };
  return (
    <div className="flex flex-col gap-2 text-xs">
      <Refresher active={items.some((a) => a.status === "building")} />
      {items.length ? (
        <ul className="flex flex-col divide-y divide-line">
          {items.map((a) => (
            <li key={a.id} className="flex flex-wrap items-center gap-2 py-1.5">
              <StatusBadge status={TONE[a.status]} label={a.status === "building" ? "Rendering" : undefined} />
              <span>{a.codec === "vp9" ? "WebM (VP9)" : "MP4 (H.264)"}{a.width ? ` · ${a.width}×${a.height}` : ""}{a.frames ? ` · ${a.frames} frames` : ""}</span>
              <span className="text-ink-3">{a.size_bytes ? formatBytes(a.size_bytes) : ""} · {formatDateTime(a.created_at)}</span>
              {a.status === "ready" ? (
                <span className="ml-auto flex items-center gap-1.5">
                  <button type="button" onClick={() => watch(a.id)} aria-pressed={playing?.id === a.id}
                          className="inline-flex h-[28px] items-center rounded-md border border-line-strong px-2.5 font-medium hover:bg-hover">
                    {playing?.id === a.id ? "Close" : "▶ Watch"}
                  </button>
                  <DownloadAnnotated id={a.id} label="Download" />
                </span>
              ) : null}
              {a.error ? <span className="w-full text-error">{a.error}</span> : null}
            </li>
          ))}
        </ul>
      ) : <p className="text-ink-3">No annotated video yet.{hasRuns ? "" : " Run hand tracking first (a pipeline, or the Hand Tracking page)."}</p>}
      {playing ? (
        <video key={playing.url} src={playing.url} controls autoPlay muted playsInline className="w-full rounded-md border border-line bg-ink" data-testid="annotated-player">
          Your browser can&apos;t play this format here; download it instead.
        </video>
      ) : null}
      {canEdit && hasRuns ? (
        <div className="flex flex-wrap items-center gap-2">
          <label htmlFor="render-codec" className="text-ink-2">Format</label>
          <select id="render-codec" value={codec} onChange={(e) => setCodec(e.target.value as "h264" | "vp9")} className="h-[28px] rounded-md border border-line-strong bg-canvas px-2">
            <option value="h264">MP4 (H.264, plays everywhere)</option>
            <option value="vp9">WebM (VP9)</option>
          </select>
          <button type="button" disabled={busy} onClick={render} className="inline-flex h-[28px] items-center rounded-md border border-line-strong px-2.5 font-medium hover:bg-hover disabled:opacity-50">
            {busy ? "Starting…" : "Render annotated video"}
          </button>
          {error ? <span role="alert" className="text-error">{error}</span> : null}
        </div>
      ) : null}
    </div>
  );
}
