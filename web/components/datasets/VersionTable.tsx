"use client";

import Link from "next/link";
import { StatusBadge } from "@/components/ui";
import type { VersionSummary } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { fullCounts, shortHash, SPLITS } from "@/lib/datasets";
import { Refresher } from "./Refresher";

const TONE = { building: "running", ready: "succeeded", failed: "failed" } as const;

/** Dataset versions, newest first; refreshes while any is still building. */
export function VersionTable({ versions }: { versions: VersionSummary[] }) {
  const building = versions.some((v) => v.status === "building");
  if (!versions.length) return <p className="py-6 text-center text-xs text-ink-3">No versions yet. Build one in the Dataset Builder.</p>;
  return (
    <div className="overflow-x-auto rounded-lg border border-line">
      <Refresher active={building} />
      <table className="w-full min-w-[760px] text-xs" data-testid="versions">
        <thead className="bg-subtle text-left text-ink-3">
          <tr><th className="px-3 py-2 font-semibold">Version</th><th className="font-semibold">Status</th><th className="text-right font-semibold">Samples</th>
            {SPLITS.map((s) => <th key={s} className="text-right font-semibold capitalize">{s}</th>)}<th className="pl-4 font-semibold">Content hash</th><th className="font-semibold">Built</th><th className="pr-3 font-semibold">By</th></tr>
        </thead>
        <tbody>
          {versions.map((v) => (
            <tr key={v.id} className="border-t border-line hover:bg-hover" data-version={v.id}>
              <td className="px-3 py-2"><Link href={`/datasets/versions/${v.id}`} className="font-semibold hover:underline">{v.dataset.name} v{v.number}</Link>{v.note ? <div className="max-w-64 truncate text-ink-3">{v.note}</div> : null}</td>
              <td><StatusBadge status={TONE[v.status]} />{v.status === "failed" && v.error ? <div className="max-w-48 truncate text-error" title={v.error}>{v.error}</div> : null}</td>
              <td className="text-right tabular-nums">{v.status === "ready" ? v.sample_count : "—"}</td>
              {SPLITS.map((s) => <td key={s} className="text-right tabular-nums text-ink-2">{v.status === "ready" ? fullCounts(v.counts).splits[s] : "—"}</td>)}
              <td className="pl-4 font-mono text-[11px] text-ink-2" title={v.content_hash ?? undefined}>{shortHash(v.content_hash)}</td>
              <td className="text-ink-2">{v.built_at ? formatDateTime(v.built_at) : v.status === "building" ? "building…" : "—"}</td>
              <td className="pr-3 text-ink-2">{v.created_by?.name ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
