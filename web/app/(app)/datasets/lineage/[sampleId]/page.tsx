import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { LineageView } from "@/components/datasets/LineageView";
import { PageHeader } from "@/components/ui";
import { ErrorPanel } from "@/components/ui/ErrorPanel";
import { api } from "@/lib/api/client";
import { requireSession } from "@/lib/auth/session";

export const metadata: Metadata = { title: "Sample lineage" };

export default async function SampleLineagePage({ params }: PageProps<"/datasets/lineage/[sampleId]">) {
  const { sampleId } = await params;
  const session = await requireSession(`/datasets/lineage/${sampleId}`);
  if (!session) return null;
  const [sample, graph] = await Promise.all([api.datasetSample(session.token, sampleId), api.sampleLineage(session.token, sampleId)]);
  if (!sample.ok && sample.kind === "http" && (sample.status === 404 || sample.status === 422)) notFound();
  if (!sample.ok) return <ErrorPanel title="Sample couldn't be loaded" message={sample.message} />;
  const s = sample.data;
  return (
    <div className="flex max-w-[1760px] flex-col gap-5">
      <div className="flex flex-col gap-1">
        <div className="text-xs text-ink-3"><Link href="/datasets/lineage" className="hover:text-ink">Lineage</Link> / <Link href={`/datasets/versions/${s.version_id}`} className="hover:text-ink">version</Link> / sample #{s.sample_no}</div>
        <PageHeader
          title={`Sample #${s.sample_no} · ${s.class_name.replace(/_/g, " ")}`}
          description={`${s.split} split · frames ${s.start_frame}–${s.end_frame} (${s.start_s.toFixed(2)}–${s.end_s.toFixed(2)} s) · ${s.handedness} hand${s.object_label ? ` · ${s.object_label}` : ""} · ${s.status.replace(/_/g, " ")}`}
          actions={<Link href={`/annotation/inspector/${s.video_id}?frame=${s.start_frame}`} className="inline-flex h-[30px] items-center rounded-md border border-line-strong px-3 font-medium hover:bg-hover">Open the frames</Link>}
        />
      </div>
      {graph.ok ? <LineageView graph={graph.data} /> : <ErrorPanel title="Lineage couldn't be loaded" message={graph.message} />}
    </div>
  );
}
