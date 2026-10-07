import type { Metadata } from "next";
import Link from "next/link";
import { DatasetBuilder } from "@/components/datasets/DatasetBuilder";
import { PageHeader } from "@/components/ui";
import { ErrorPanel } from "@/components/ui/ErrorPanel";
import { api } from "@/lib/api/client";
import { requireSession } from "@/lib/auth/session";
import { pickQuery } from "@/lib/query";

export const metadata: Metadata = { title: "Dataset Builder" };

export default async function DatasetBuilderPage({ searchParams }: PageProps<"/datasets/builder">) {
  const session = await requireSession("/datasets/builder");
  if (!session) return null;
  const query = pickQuery(await searchParams, ["dataset"]);
  const [datasets, sessions, devices, classes, facets] = await Promise.all([
    api.datasets(session.token),
    api.sessions(session.token, { limit: 200, sort: "created_at", order: "desc" }),
    api.devices(session.token, { limit: 200 }),
    api.movementClasses(session.token),
    api.datasetFacets(session.token),
  ]);
  const failed = [datasets, sessions, devices, classes, facets].find((r) => !r.ok);
  return (
    <div className="flex max-w-[1760px] flex-col gap-5">
      <PageHeader
        eyebrow="Datasets"
        title="Dataset Builder"
        description="Choose what goes into a training set and how it splits. Each version records its filters, the exact videos and model runs it read, and the moment it was built, so it can always be rebuilt to the same hash."
        actions={<Link href="/datasets/versions" className="inline-flex h-[30px] items-center rounded-md border border-line-strong px-3 font-medium hover:bg-hover">All versions</Link>}
      />
      {session.user.role === "viewer" ? (
        <ErrorPanel title="Viewers can't build datasets" message="Ask an admin for the annotator or reviewer role. Built versions are under Versions." />
      ) : failed || !datasets.ok || !sessions.ok || !devices.ok || !classes.ok || !facets.ok ? (
        <ErrorPanel title="The builder couldn't load" message={failed && !failed.ok ? failed.message : ""} />
      ) : (
        <DatasetBuilder
          datasets={datasets.data.items}
          sessions={sessions.data.items.map((s) => ({ id: s.id, name: s.name }))}
          devices={devices.data.items.map((d) => ({ id: d.id, name: d.name }))}
          classes={classes.data}
          facets={facets.data}
          initialDataset={query.dataset ?? (datasets.data.items.length ? undefined : "__new")}
        />
      )}
    </div>
  );
}
