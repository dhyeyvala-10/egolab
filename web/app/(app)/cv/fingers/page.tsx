import type { Metadata } from "next";
import Link from "next/link";
import { RunTable } from "@/components/cv/RunTable";
import { PageHeader } from "@/components/ui";
import { ErrorPanel } from "@/components/ui/ErrorPanel";
import { api } from "@/lib/api/client";
import { requireSession } from "@/lib/auth/session";
import { pickQuery } from "@/lib/query";

export const metadata: Metadata = { title: "Finger Tracking" };

export default async function FingerTrackingPage({ searchParams }: PageProps<"/cv/fingers">) {
  const session = await requireSession("/cv/fingers");
  if (!session) return null;
  const query = pickQuery(await searchParams, ["status", "offset"]);
  const runs = await api.cvRuns(session.token, { status: "succeeded", ...query, kind: "hand_tracking", limit: 50 });
  return (
    <div className="flex max-w-[1760px] flex-col gap-5">
      <PageHeader
        eyebrow="Computer Vision"
        title="Finger Tracking"
        description="Per-finger kinematics from hand tracking runs: fingertip speed and acceleration, visibility, and estimated occlusion."
      />
      {runs.ok ? (
        <RunTable
          page={runs.data}
          query={query}
          base="/cv/fingers"
          emptyAction={<Link href="/cv/hands" className="inline-flex h-[30px] items-center rounded-md border border-line-strong px-3 font-medium hover:bg-hover">Run hand tracking</Link>}
        />
      ) : (
        <ErrorPanel title="Runs couldn't be loaded" message={runs.message} />
      )}
    </div>
  );
}
