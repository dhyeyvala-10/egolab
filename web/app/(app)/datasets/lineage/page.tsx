import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { EmptyState, PageHeader } from "@/components/ui";
import { ErrorPanel } from "@/components/ui/ErrorPanel";
import { Panel } from "@/components/ui/Panel";
import { api } from "@/lib/api/client";
import { requireSession } from "@/lib/auth/session";
import { pickQuery } from "@/lib/query";

export const metadata: Metadata = { title: "Lineage" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Find a sample to trace: by id, or from a version's samples. */
export default async function LineagePage({ searchParams }: PageProps<"/datasets/lineage">) {
  const session = await requireSession("/datasets/lineage");
  if (!session) return null;
  const query = pickQuery(await searchParams, ["sample", "version"]);
  if (query.sample && UUID.test(query.sample.trim())) redirect(`/datasets/lineage/${query.sample.trim()}`);
  const versions = await api.datasetVersions(session.token, { status: "ready", limit: 50 });
  const version = query.version ?? (versions.ok ? versions.data.items[0]?.id : undefined);
  const samples = version ? await api.versionSamples(session.token, version, { limit: 25 }) : null;
  return (
    <div className="flex max-w-[1200px] flex-col gap-5">
      <PageHeader
        eyebrow="Datasets"
        title="Lineage"
        description="Trace any exported sample back through its annotation and review, the model runs and versions that produced it, the jobs, the video, and the raw file and frames. Every export carries each sample's id."
      />
      <form action="/datasets/lineage" className="flex flex-wrap items-center gap-2 text-xs">
        <label htmlFor="sample" className="text-ink-2">Sample id</label>
        <input id="sample" name="sample" defaultValue={query.sample ?? ""} placeholder="e.g. from samples.jsonl or a COCO annotation" className="h-[30px] w-96 max-w-full rounded-md border border-line-strong px-2 font-mono" />
        <button type="submit" className="h-[30px] rounded-md bg-ink px-3 font-semibold text-canvas">Trace</button>
        {query.sample && !UUID.test(query.sample.trim()) ? <span className="text-error">That isn&apos;t a sample id.</span> : null}
      </form>
      {!versions.ok ? <ErrorPanel title="Versions couldn't be loaded" message={versions.message} /> : !versions.data.items.length ? (
        <EmptyState title="No dataset versions yet" description={<>Build one in the <Link href="/datasets/builder" className="underline">Dataset Builder</Link>, then trace its samples here.</>} />
      ) : (
        <Panel title="Or pick a sample" actions={
          <form action="/datasets/lineage" className="flex items-center gap-2 text-xs">
            <select name="version" defaultValue={version} aria-label="Version" className="h-7 rounded-md border border-line-strong bg-canvas px-2">
              {versions.data.items.map((v) => <option key={v.id} value={v.id}>{v.dataset.name} v{v.number}</option>)}
            </select>
            <button type="submit" className="h-7 rounded-md border border-line-strong px-2 font-medium">Show</button>
          </form>}>
          {samples?.ok ? (
            <ul className="divide-y divide-line text-xs" data-testid="pick-samples">
              {samples.data.items.map((s) => (
                <li key={s.id} className="flex flex-wrap items-center gap-2 py-1.5">
                  <span className="w-10 tabular-nums text-ink-3">#{s.sample_no}</span>
                  <span className="font-medium">{s.class_name.replace(/_/g, " ")}</span>
                  <span className="font-mono text-ink-2">f{s.start_frame}–f{s.end_frame}</span>
                  <span className="capitalize text-ink-2">{s.split}</span>
                  <Link href={`/datasets/lineage/${s.id}`} className="ml-auto font-semibold underline">Trace</Link>
                </li>
              ))}
            </ul>
          ) : <p className="text-xs text-ink-3">No samples.</p>}
        </Panel>
      )}
    </div>
  );
}
