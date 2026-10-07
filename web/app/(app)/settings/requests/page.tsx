import type { Metadata } from "next";
import { AutoRefresh } from "@/components/data/AutoRefresh";
import { AdminOnly } from "@/components/settings/AdminOnly";
import { RequestList } from "@/components/settings/RequestList";
import { PageHeader } from "@/components/ui";
import { ErrorPanel } from "@/components/ui/ErrorPanel";
import { api } from "@/lib/api/client";
import { requireAdmin } from "@/lib/auth/admin";

export const metadata: Metadata = { title: "Requests" };

export default async function RequestsPage() {
  const { session, allowed } = await requireAdmin("/settings/requests");
  if (!session) return null;
  const header = (
    <PageHeader
      eyebrow="Settings"
      title="Requests"
      description="An upload over your size limit waits here before any of it is sent; a video over your length limit waits here before anything processes it."
    />
  );
  if (!allowed) return <div className="flex max-w-[1100px] flex-col gap-5">{header}<AdminOnly /></div>;
  const requests = await api.requests(session.token);
  return (
    <div className="flex max-w-[1100px] flex-col gap-5">
      {header}
      <AutoRefresh everyMs={10_000} />
      {requests.ok ? <RequestList uploads={requests.data.uploads} videos={requests.data.videos} /> : <ErrorPanel title="Requests couldn't be loaded" message={requests.message} />}
    </div>
  );
}
