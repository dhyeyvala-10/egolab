import type { Metadata } from "next";
import Link from "next/link";
import { ClassEditor } from "@/components/movement/ClassEditor";
import { PageHeader } from "@/components/ui";
import { ErrorPanel } from "@/components/ui/ErrorPanel";
import { api } from "@/lib/api/client";
import { requireSession } from "@/lib/auth/session";

export const metadata: Metadata = { title: "Movement classes" };

export default async function MovementClassesPage() {
  const session = await requireSession("/cv/movements/classes");
  if (!session) return null;
  const classes = await api.movementClasses(session.token);
  const canEdit = session.user.role === "admin" || session.user.role === "reviewer";
  return (
    <div className="flex max-w-[1200px] flex-col gap-5">
      <div className="flex flex-col gap-1">
        <div className="text-xs text-ink-3"><Link href="/cv/movements" className="hover:text-ink">Movement Classification</Link> / Classes</div>
        <PageHeader
          title="Movement classes"
          description="The classes events are labelled with. Relabel or describe any class, switch off the ones you don't record (new runs skip them; existing events stay), and add your own. A class's name is fixed: classifiers emit it."
        />
      </div>
      {classes.ok ? <ClassEditor classes={classes.data} canEdit={canEdit} /> : <ErrorPanel title="Classes couldn't be loaded" message={classes.message} />}
      {!canEdit ? <p className="text-xs text-ink-3">Admins and reviewers can edit classes.</p> : null}
    </div>
  );
}
