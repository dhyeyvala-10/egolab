import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Refresher } from "@/components/datasets/Refresher";
import { SplitBar } from "@/components/datasets/SplitBar";
import { ExportPanel, RebuildCheck } from "@/components/datasets/VersionActions";
import { PageHeader, StatCard, StatusBadge } from "@/components/ui";
import { ErrorPanel } from "@/components/ui/ErrorPanel";
import { KeyValues } from "@/components/ui/KeyValues";
import { Panel } from "@/components/ui/Panel";
import { api } from "@/lib/api/client";
import { requireSession } from "@/lib/auth/session";
import { describeFilters, fullCounts, SPLITS } from "@/lib/datasets";
import { formatDateTime } from "@/lib/format";
import { pickQuery } from "@/lib/query";

export const metadata: Metadata = { title: "Dataset version" };

const TONE = { building: "running", ready: "succeeded", failed: "failed" } as const;
const PAGE = 50;

export default async function VersionPage({ params, searchParams }: PageProps<"/datasets/versions/[id]">) {
  const { id } = await params;
  const session = await requireSession(`/datasets/versions/${id}`);
  if (!session) return null;
  const query = pickQuery(await searchParams, ["split", "class", "offset"]);
  const res = await api.datasetVersion(session.token, id);
  if (!res.ok && res.kind === "http" && (res.status === 404 || res.status === 422)) notFound();
  if (!res.ok) return <ErrorPanel title="Version couldn't be loaded" message={res.message} />;
  const v = res.data;
  const counts = fullCounts(v.counts);
  const offset = Math.max(0, Number(query.offset) || 0);
  const [samples, checks, exports, facets, sessions, devices, classes] = await Promise.all([
    api.versionSamples(session.token, id, { split: query.split, class: query.class, limit: PAGE, offset }),
    api.versionChecks(session.token, id),
    api.datasetExports(session.token, { version_id: id, limit: 50 }),
    api.datasetFacets(session.token),
    api.sessions(session.token, { limit: 200 }),
    api.devices(session.token, { limit: 200 }),
    api.movementClasses(session.token),
  ]);
  const names: Record<string, string> = Object.fromEntries([
    ...(sessions.ok ? sessions.data.items.map((s) => [s.id, s.name]) : []),
    ...(devices.ok ? devices.data.items.map((d) => [d.id, d.name]) : []),
  ]);
  const labels: Record<string, string> = Object.fromEntries(classes.ok ? classes.data.map((c) => [c.name, c.label]) : []);
  const canRun = session.user.role !== "viewer";
  const inputs = v.inputs as { as_of?: string; videos?: { id: string }[]; runs?: string[]; hash_version?: string };
  const link = (patch: Record<string, string | undefined>) => {
    const p = new URLSearchParams(Object.entries({ ...query, ...patch }).filter(([, x]) => x) as [string, string][]);
    return `/datasets/versions/${id}${p.size ? `?${p}` : ""}`;
  };

  return (
    <div className="flex max-w-[1760px] flex-col gap-5">
      <div className="flex flex-col gap-1">
        <div className="text-xs text-ink-3"><Link href="/datasets/versions" className="hover:text-ink">Versions</Link> / {v.dataset.name}</div>
        <PageHeader
          title={`${v.dataset.name} v${v.number}`}
          description={
            <span className="flex flex-wrap items-center gap-2">
              <StatusBadge status={TONE[v.status]} />
              <span className="font-mono text-xs text-ink-2 break-all" data-testid="content-hash">{v.content_hash ?? "no hash yet"}</span>
            </span>
          }
          actions={<Link href={`/datasets/builder?dataset=${v.dataset.id}`} className="inline-flex h-[30px] items-center rounded-md border border-line-strong px-3 font-medium hover:bg-hover">Build the next version</Link>}
        />
        {v.note ? <p className="text-sm text-ink-2">{v.note}</p> : null}
        {v.status === "failed" ? <p className="text-xs text-error">The build failed: {v.error}</p> : null}
        {v.status === "building" ? <p className="text-xs text-ink-2">Building… this page refreshes when it is ready.</p> : null}
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard label="Samples" value={v.status === "ready" ? v.sample_count : null} />
        <StatCard label="Videos" value={v.status === "ready" ? counts.videos : (inputs.videos?.length ?? null)} hint={`${inputs.runs?.length ?? 0} classification runs pinned`} />
        <StatCard label="Corrections" value={v.status === "ready" ? (counts.sources.auto_corrected ?? 0) : null} hint="A person's corrections in place of predictions" />
        <StatCard label="Parent" value={v.parent_version_id ? `v${v.number - 1}` : "—"} href={v.parent_version_id ? `/datasets/versions/${v.parent_version_id}` : undefined} />
      </div>
      {v.status === "ready" ? <SplitBar counts={v.counts} /> : null}

      <div className="grid items-start gap-4 lg:grid-cols-2">
        <Panel title="Recorded spec" hint="What was asked">
          <ul className="flex flex-col gap-1 py-1 text-xs" data-testid="spec">{describeFilters(v.spec, names).map((l) => <li key={l}>{l}</li>)}</ul>
          <details className="mt-1 text-xs"><summary className="cursor-pointer text-ink-2">JSON</summary><pre className="mt-1 max-h-64 overflow-auto rounded bg-subtle p-2 font-mono text-[11px]">{JSON.stringify(v.spec, null, 2)}</pre></details>
        </Panel>
        <Panel title="Pinned inputs" hint="What it was built from">
          <KeyValues rows={[
            ["As of", inputs.as_of ? <span key="a" className="font-mono text-xs">{inputs.as_of}</span> : null],
            ["Videos", `${inputs.videos?.length ?? 0}`],
            ["Classification runs", <span key="r" className="font-mono text-[11px]">{(inputs.runs ?? []).map((r) => r.slice(0, 8)).join(" ") || "—"}</span>],
            ["Model versions", <span key="m" className="text-xs">{v.model_versions.map((m) => `${m.name} ${m.version}`).join(" · ") || "—"}</span>],
            ["Hash format", inputs.hash_version ?? null],
            ["Built", v.built_at ? `${formatDateTime(v.built_at)}${v.created_by ? ` by ${v.created_by.name}` : ""}` : null],
          ]} />
        </Panel>
      </div>

      {v.status === "ready" ? (
        <>
          <Panel title="Reproducibility" hint="Rebuild from the recorded spec and inputs, and compare hashes">
            {checks.ok ? <RebuildCheck versionId={v.id} hash={v.content_hash} checks={checks.data} canRun={canRun} /> : <p className="text-xs text-error">{checks.message}</p>}
          </Panel>
          <Panel title="Exports">
            {exports.ok && facets.ok ? <ExportPanel versionId={v.id} exports={exports.data.items} formats={facets.data.formats} canRun={canRun} /> : <p className="text-xs text-error">Exports couldn&apos;t be loaded.</p>}
          </Panel>
          <Panel title="Classes" hint="Samples per class and split">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[420px] text-xs" data-testid="class-splits">
                <thead className="text-left text-ink-3"><tr><th className="py-1 font-semibold">Class</th>{SPLITS.map((s) => <th key={s} className="text-right font-semibold capitalize">{s}</th>)}<th className="text-right font-semibold">Total</th></tr></thead>
                <tbody>
                  {Object.entries(counts.classes).map(([c, n]) => (
                    <tr key={c} className="border-t border-line"><td className="py-1"><Link href={link({ class: c, offset: undefined })} className="hover:underline">{labels[c] ?? c}</Link></td>{SPLITS.map((s) => <td key={s} className="text-right tabular-nums">{n[s]}</td>)}<td className="text-right tabular-nums font-medium">{SPLITS.reduce((t, s) => t + n[s], 0)}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
          <Panel title="Samples" hint={samples.ok ? `${samples.data.total} ${query.split ?? ""} ${query.class ? labels[query.class] ?? query.class : ""}`.replace(/\s+/g, " ").trim() : undefined}
                 actions={<div className="flex gap-1 text-xs">{[undefined, ...SPLITS].map((s) => (
                   <Link key={s ?? "all"} href={link({ split: s, offset: undefined })} aria-current={query.split === s ? "page" : undefined}
                         className={query.split === s ? "rounded-md bg-ink px-2 py-1 font-semibold text-canvas" : "rounded-md border border-line-strong px-2 py-1 hover:bg-hover"}>{s ?? "All"}</Link>))}
                   {query.class ? <Link href={link({ class: undefined, offset: undefined })} className="rounded-md border border-line-strong px-2 py-1 hover:bg-hover">× {labels[query.class] ?? query.class}</Link> : null}</div>}>
            {samples.ok ? (
              <>
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[820px] text-xs" data-testid="samples">
                    <thead className="text-left text-ink-3"><tr><th className="py-1 font-semibold">#</th><th className="font-semibold">Split</th><th className="font-semibold">Class</th><th className="font-semibold">Frames</th><th className="font-semibold">Hand</th><th className="font-semibold">Object</th><th className="font-semibold">Review</th><th className="text-right font-semibold">Confidence</th><th className="pl-3 font-semibold">Lineage</th></tr></thead>
                    <tbody>
                      {samples.data.items.map((s) => (
                        <tr key={s.id} className="border-t border-line" data-sample={s.id}>
                          <td className="py-1.5 tabular-nums text-ink-3">{s.sample_no}</td>
                          <td className="capitalize">{s.split}</td>
                          <td className="font-medium">{labels[s.class_name] ?? s.class_name}{s.source === "auto_corrected" ? <span className="ml-1 text-human">corrected</span> : null}</td>
                          <td className="font-mono">f{s.start_frame}–f{s.end_frame}</td>
                          <td>{s.handedness}</td>
                          <td>{s.object_label ?? <span className="text-ink-3">—</span>}</td>
                          <td>{s.status.replace(/_/g, " ")}{s.review_method ? <span className="text-ink-3"> · {s.review_method.replace(/_/g, " ")}</span> : null}</td>
                          <td className="text-right tabular-nums">{s.confidence != null ? s.confidence.toFixed(2) : "—"}</td>
                          <td className="pl-3"><Link href={`/datasets/lineage/${s.id}`} className="font-semibold underline">Trace</Link></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="flex items-center justify-between pt-2 text-xs text-ink-2">
                  <span>{samples.data.total ? `${offset + 1}–${Math.min(offset + PAGE, samples.data.total)} of ${samples.data.total}` : "No samples"}</span>
                  <span className="flex gap-2">
                    {offset > 0 ? <Link href={link({ offset: String(Math.max(0, offset - PAGE)) })} className="underline">Previous</Link> : null}
                    {offset + PAGE < samples.data.total ? <Link href={link({ offset: String(offset + PAGE) })} className="underline">Next</Link> : null}
                  </span>
                </div>
              </>
            ) : <p className="text-xs text-error">{samples.message}</p>}
          </Panel>
        </>
      ) : null}
      <Refresher active={v.status === "building"} />
    </div>
  );
}
