import type { Metadata } from "next";
import Link from "next/link";
import { VersionTable } from "@/components/datasets/VersionTable";
import { PageHeader, StatCard } from "@/components/ui";
import { ErrorPanel } from "@/components/ui/ErrorPanel";
import { api } from "@/lib/api/client";
import { requireSession } from "@/lib/auth/session";
import { pickQuery } from "@/lib/query";

export const metadata: Metadata = { title: "Dataset versions" };

export default async function VersionsPage({ searchParams }: PageProps<"/datasets/versions">) {
  const session = await requireSession("/datasets/versions");
  if (!session) return null;
  const query = pickQuery(await searchParams, ["dataset_id"]);
  const [versions, datasets, exports] = await Promise.all([
    api.datasetVersions(session.token, { dataset_id: query.dataset_id, limit: 100 }),
    api.datasets(session.token),
    api.datasetExports(session.token, { limit: 1 }),
  ]);
  const ready = versions.ok ? versions.data.items.filter((v) => v.status === "ready") : [];
  return (
    <div className="flex max-w-[1760px] flex-col gap-5">
      <PageHeader
        eyebrow="Datasets"
        title="Versions"
        description="Every dataset version: immutable once built, with the filters, inputs, model versions, and content hash it was built from."
        actions={<Link href="/datasets/builder" className="inline-flex h-[30px] items-center rounded-md bg-ink px-3 font-semibold text-canvas hover:opacity-90">Build a version</Link>}
      />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard label="Datasets" value={datasets.ok ? datasets.data.total : null} />
        <StatCard label="Versions" value={versions.ok ? versions.data.total : null} hint={query.dataset_id ? "in this dataset" : undefined} />
        <StatCard label="Samples (latest shown)" value={ready[0]?.sample_count ?? null} hint={ready[0] ? `${ready[0].dataset.name} v${ready[0].number}` : undefined} />
        <StatCard label="Exports" value={exports.ok ? exports.data.total : null} href="/datasets/exports" />
      </div>
      {datasets.ok && datasets.data.items.length > 1 ? (
        <form action="/datasets/versions" className="flex items-center gap-2 text-xs">
          <label htmlFor="dataset_id" className="text-ink-2">Dataset</label>
          <select id="dataset_id" name="dataset_id" defaultValue={query.dataset_id ?? ""} className="h-[30px] rounded-md border border-line-strong bg-canvas px-2">
            <option value="">All datasets</option>
            {datasets.data.items.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
          <button type="submit" className="h-[30px] rounded-md border border-line-strong px-3 font-medium hover:bg-hover">Show</button>
        </form>
      ) : null}
      {versions.ok ? <VersionTable versions={versions.data.items} /> : <ErrorPanel title="Versions couldn't be loaded" message={versions.message} />}
    </div>
  );
}
