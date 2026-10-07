"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { StatusBadge } from "@/components/ui";
import { browserApi } from "@/lib/api/browser";
import type { CheckRead, ExportDownload, ExportRead } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { FORMAT_INFO, shortHash } from "@/lib/datasets";
import { Refresher } from "./Refresher";
import { formatBytes, formatDateTime } from "@/lib/format";

const TONE = { building: "running", ready: "succeeded", failed: "failed" } as const;


export async function download(id: string): Promise<string | null> {
  const res = await browserApi<ExportDownload>(`/datasets/exports/${id}/download`);
  if (!res.ok) return res.message;
  const a = document.createElement("a");
  a.href = res.data.url;
  a.download = res.data.filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  return null;
}

/**
 * Rebuild the version from its recorded spec and inputs, and compare the content hash with the one it was
 * built with (spec Phase 6 acceptance).
 */
export function RebuildCheck({ versionId, hash, checks, canRun }: { versionId: string; hash: string | null; checks: CheckRead[]; canRun: boolean }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    const res = await browserApi<CheckRead>(`/datasets/versions/${versionId}/checks`, { method: "POST" });
    setBusy(false);
    setError(res.ok ? null : res.message);
    router.refresh();
  };
  const last = checks[0];
  return (
    <div className="flex flex-col gap-2 text-xs" data-testid="checks">
      <Refresher active={checks.some((c) => c.status === "building")} />
      <div className="flex flex-wrap items-center gap-2">
        {canRun ? <button type="button" onClick={() => void run()} disabled={busy} className="h-[30px] rounded-md border border-line-strong px-3 font-semibold hover:bg-hover disabled:opacity-50">Rebuild from spec</button> : null}
        {last ? (
          last.status === "building" ? <span className="text-ink-2">Rebuilding…</span>
          : last.status === "failed" ? <span className="text-error">The rebuild failed: {last.error}</span>
          : <span className={cn("font-semibold", last.matches ? "text-success" : "text-error")} data-testid="check-result">
              {last.matches ? "✓ Identical hash" : "✗ Different hash"} <span className="font-mono font-normal text-ink-2">{shortHash(last.content_hash)}</span>
            </span>
        ) : <span className="text-ink-3">Not rebuilt yet.</span>}
      </div>
      {checks.length ? (
        <ul className="flex flex-col gap-0.5 text-ink-2">
          {checks.slice(0, 5).map((c) => (
            <li key={c.id} className="flex flex-wrap gap-x-2">
              <span className="tabular-nums">{formatDateTime(c.created_at)}</span>
              <span>{c.status === "ready" ? (c.matches ? "identical" : "different") : c.status}</span>
              {c.content_hash ? <span className="font-mono">{c.content_hash === hash ? "= recorded hash" : shortHash(c.content_hash)}</span> : null}
              {c.sample_count != null ? <span>{c.sample_count} samples</span> : null}
            </li>
          ))}
        </ul>
      ) : null}
      {error ? <p className="text-error">{error}</p> : null}
    </div>
  );
}

/** Start an export in any format, and download finished ones. */
export function ExportPanel({ versionId, exports, formats, canRun }: { versionId: string; exports: ExportRead[]; formats: string[]; canRun: boolean }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const start = async (format: string) => {
    setBusy(format);
    const res = await browserApi<ExportRead>(`/datasets/versions/${versionId}/exports`, { method: "POST", body: { format } });
    setBusy(null);
    setError(res.ok ? null : res.message);
    router.refresh();
  };
  return (
    <div className="flex flex-col gap-3 text-xs">
      <Refresher active={exports.some((e) => e.status === "building")} />
      {canRun ? (
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5" role="group" aria-label="Export formats">
          {formats.map((f) => (
            <button key={f} type="button" onClick={() => void start(f)} disabled={busy !== null}
                    className="flex flex-col items-start gap-0.5 rounded-md border border-line-strong px-3 py-2 text-left hover:bg-hover disabled:opacity-50" data-format={f}>
              <span className="font-semibold">{FORMAT_INFO[f]?.label ?? f}</span>
              <span className="text-ink-3">{FORMAT_INFO[f]?.hint}</span>
            </button>
          ))}
        </div>
      ) : null}
      {exports.length ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px]" data-testid="exports">
            <thead className="text-left text-ink-3"><tr><th className="py-1 font-semibold">Format</th><th className="font-semibold">Status</th><th className="text-right font-semibold">Size</th><th className="text-right font-semibold">Files</th><th className="pl-3 font-semibold">sha256</th><th className="font-semibold">Started</th><th /></tr></thead>
            <tbody>
              {exports.map((e) => (
                <tr key={e.id} className="border-t border-line" data-export={e.format}>
                  <td className="py-1.5 font-medium">{FORMAT_INFO[e.format]?.label ?? e.format}</td>
                  <td><StatusBadge status={TONE[e.status]} />{e.error ? <span className="ml-1 text-error">{e.error}</span> : null}</td>
                  <td className="text-right tabular-nums">{formatBytes(e.size_bytes)}</td>
                  <td className="text-right tabular-nums">{e.files ?? "—"}</td>
                  <td className="pl-3 font-mono text-[11px] text-ink-2" title={e.sha256 ?? undefined}>{shortHash(e.sha256)}</td>
                  <td className="text-ink-2">{formatDateTime(e.created_at)}</td>
                  <td className="text-right">{e.status === "ready" ? <button type="button" onClick={() => void download(e.id).then(setError)} className="font-semibold underline">Download</button> : null}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <p className="text-ink-3">No exports of this version yet.</p>}
      {error ? <p className="text-error">{error}</p> : null}
    </div>
  );
}
