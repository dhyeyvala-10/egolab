import type { Metadata } from "next";
import { AutoRefresh } from "@/components/data/AutoRefresh";
import { UploadList } from "@/components/data/UploadList";
import { Uploader } from "@/components/data/Uploader";
import { PageHeader } from "@/components/ui";
import { ErrorPanel } from "@/components/ui/ErrorPanel";
import { api } from "@/lib/api/client";
import { requireSession } from "@/lib/auth/session";
import { pickQuery } from "@/lib/query";

export const metadata: Metadata = { title: "Upload" };

export default async function UploadPage({ searchParams }: PageProps<"/data/upload">) {
  const session = await requireSession("/data/upload");
  if (!session) return null;
  const { session: defaultSession } = pickQuery(await searchParams, ["session"]);
  const [sessions, uploads, limits] = await Promise.all([
    api.sessions(session.token, { limit: 200, sort: "created_at", order: "desc" }),
    api.uploads(session.token, { limit: 20 }),
    api.limits(session.token),
  ]);
  const refs = sessions.ok ? sessions.data.items.map((s) => ({ id: s.id, name: s.name })) : [];
  const { role, id: me } = session.user;
  const isAdmin = role === "admin";
  const canWrite = role === "admin" || role === "annotator" || role === "reviewer";
  // Keep the list current by itself while anything is on its way in or being processed.
  const busy = uploads.ok && uploads.data.items.some((u) => ["uploading", "processing", "awaiting_approval"].includes(u.status));
  const sizeLimit = limits.ok && !isAdmin ? limits.data.upload_max_bytes : null;

  return (
    <div className="flex max-w-[1100px] flex-col gap-5">
      <PageHeader
        eyebrow="Data"
        title="Upload"
        description="Each file is checksummed after upload. An exact duplicate links to the existing video instead of being stored again; unreadable files are flagged, not dropped."
      />
      {canWrite ? (
        <Uploader sessions={refs} defaultSessionId={defaultSession} sizeLimit={sizeLimit ?? null} />
      ) : (
        <ErrorPanel title="Viewers can't upload" message="Ask the admin to give you the annotator or reviewer role." />
      )}
      <AutoRefresh everyMs={5000} active={busy} />
      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold">{isAdmin ? "Recent uploads (everyone's)" : "Your recent uploads"}</h2>
        {uploads.ok ? (
          <UploadList uploads={uploads.data.items} sessions={refs} isAdmin={isAdmin} me={me} />
        ) : (
          <ErrorPanel title="Uploads couldn't be loaded" message={uploads.message} />
        )}
      </section>
    </div>
  );
}
