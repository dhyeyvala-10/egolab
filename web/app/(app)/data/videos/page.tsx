import type { Metadata } from "next";
import Link from "next/link";
import { VideoTable } from "@/components/data/VideoTable";
import { PageHeader } from "@/components/ui";
import { ErrorPanel } from "@/components/ui/ErrorPanel";
import { api } from "@/lib/api/client";
import { requireSession } from "@/lib/auth/session";
import { pickQuery } from "@/lib/query";

export const metadata: Metadata = { title: "Video Library" };

const KEYS = ["q", "status", "session_id", "unassigned", "source_kind", "sort", "order", "offset"] as const;

export default async function VideoLibraryPage({ searchParams }: PageProps<"/data/videos">) {
  const session = await requireSession("/data/videos");
  if (!session) return null;
  const query = pickQuery(await searchParams, KEYS);
  const [videos, sessions] = await Promise.all([
    api.videos(session.token, { ...query, limit: 50 }),
    api.sessions(session.token, { limit: 200, sort: "created_at", order: "desc" }),
  ]);

  return (
    <div className="flex max-w-[1760px] flex-col gap-5">
      <PageHeader
        eyebrow="Data"
        title="Video Library"
        description="Every ingested video, with metadata read by ffprobe. Duplicates are linked to the original, never stored twice."
        actions={
          <Link href="/data/upload" className="inline-flex h-[30px] items-center rounded-md bg-ink px-3 font-semibold text-canvas hover:opacity-90">
            Upload
          </Link>
        }
      />
      {videos.ok ? (
        <VideoTable
          page={videos.data}
          query={query}
          sessions={sessions.ok ? sessions.data.items.map((s) => ({ id: s.id, name: s.name })) : undefined}
          emptyAction={
            <Link href="/data/upload" className="inline-flex h-[30px] items-center rounded-md border border-line-strong px-3 font-medium hover:bg-hover">
              Upload videos
            </Link>
          }
        />
      ) : (
        <ErrorPanel title="Videos couldn't be loaded" message={videos.message} />
      )}
    </div>
  );
}
