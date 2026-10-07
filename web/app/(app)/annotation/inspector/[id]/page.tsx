import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Inspector } from "@/components/inspector/Inspector";
import { ErrorPanel } from "@/components/ui/ErrorPanel";
import { api } from "@/lib/api/client";
import { requireSession } from "@/lib/auth/session";

export const metadata: Metadata = { title: "Video Inspector" };

export default async function InspectorPage({ params, searchParams }: PageProps<"/annotation/inspector/[id]">) {
  const { id } = await params;
  const frameParam = (await searchParams).frame;
  const frame = Number(Array.isArray(frameParam) ? frameParam[0] : frameParam);
  const session = await requireSession(`/annotation/inspector/${id}`);
  if (!session) return null;
  const res = await api.video(session.token, id);
  if (!res.ok && res.kind === "http" && (res.status === 404 || res.status === 422)) notFound();
  if (!res.ok) return <ErrorPanel title="Video couldn't be loaded" message={res.message} />;
  return (
    <div className="max-w-[1840px]">
      <Inspector video={res.data} canEdit={session.user.role !== "viewer"} initialFrame={Number.isInteger(frame) && frame >= 0 ? frame : undefined} />
    </div>
  );
}
