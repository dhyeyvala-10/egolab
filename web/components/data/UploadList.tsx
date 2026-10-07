"use client";

import type { Ref, UploadRead } from "@/lib/api/types";
import { RecentUploads } from "./RecentUploads";

/** Recent uploads for the signed-in person: the admin sees and can cancel everyone's; others their own. */
export function UploadList({ uploads, sessions, isAdmin, me }: { uploads: UploadRead[]; sessions: Ref[]; isAdmin: boolean; me: string }) {
  return <RecentUploads uploads={uploads} sessions={sessions} showWho={isAdmin} canCancel={(u) => isAdmin || u.created_by === me} />;
}
