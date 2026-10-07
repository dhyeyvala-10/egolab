import type { Metadata } from "next";
import Link from "next/link";
import { ExportPanel } from "@/components/datasets/VersionActions";
import { PageHeader } from "@/components/ui";
import { ErrorPanel } from "@/components/ui/ErrorPanel";
import { Panel } from "@/components/ui/Panel";
import { api } from "@/lib/api/client";
import type { ExportRead } from "@/lib/api/types";
import { requireSession } from "@/lib/auth/session";
import { FORMAT_INFO } from "@/lib/datasets";

export const metadata: Metadata = { title: "Exports" };

export default async function ExportsPage() {
  const session = await requireSession("/datasets/exports");
  if (!session) return null;
  const exports = await api.datasetExports(session.token, { limit: 100 });
  const byVersion = new Map<string, ExportRead[]>();
  if (exports.ok) for (const e of exports.data.items) byVersion.set(e.version_id, [...(byVersion.get(e.version_id) ?? []), e]);
  return (
    <div className="flex max-w-[1200px] flex-col gap-5">
      <PageHeader
        eyebrow="Datasets"
        title="Exports"
        description="Dataset versions written out for training. Every archive carries a manifest with the version's content hash, spec, inputs, and model versions, and each sample's id for tracing it back."
      />
      <Panel title="Formats">
        <dl className="grid gap-2 py-1 text-xs sm:grid-cols-2 lg:grid-cols-5">
          {Object.entries(FORMAT_INFO).map(([k, f]) => <div key={k}><dt className="font-semibold">{f.label}</dt><dd className="text-ink-2">{f.hint}</dd></div>)}
        </dl>
      </Panel>
      {!exports.ok ? <ErrorPanel title="Exports couldn't be loaded" message={exports.message} /> : !exports.data.items.length ? (
        <p className="text-xs text-ink-3">No exports yet. Open a version under <Link href="/datasets/versions" className="underline">Versions</Link> and choose a format.</p>
      ) : (
        [...byVersion.entries()].map(([vid, list]) => (
          <Panel key={vid} title={`${list[0].dataset.name} v${list[0].version_number}`} actions={<Link href={`/datasets/versions/${vid}`} className="text-xs underline">Version</Link>}>
            <ExportPanel versionId={vid} exports={list} formats={[]} canRun={false} />
          </Panel>
        ))
      )}
    </div>
  );
}
