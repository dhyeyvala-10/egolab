import { Construction } from "lucide-react";
import Link from "next/link";
import { PHASES, type NavPage } from "@/lib/nav";
import { EmptyState } from "./EmptyState";
import { PageHeader } from "./PageHeader";

/** Placeholder for pages whose phase has not been built yet (spec Phase 0: app shell). */
export function NotYetBuilt({ page, section }: { page: NavPage; section: string }) {
  return (
    <div className="flex max-w-[1180px] flex-col gap-5">
      <PageHeader eyebrow={section} title={page.label} />
      <section className="rounded-lg border border-line">
        <EmptyState
          icon={<Construction className="size-5" aria-hidden />}
          title="Not yet built"
          description={
            <>
              <span className="block">{page.summary}</span>
              <span className="mt-2 block text-ink-3">
                Planned for Phase {page.phase} — {PHASES[page.phase]}.
              </span>
            </>
          }
          action={
            <Link href="/dashboard" className="inline-flex h-[30px] items-center rounded-md border border-line-strong px-3 font-medium hover:bg-hover">
              Back to Overview
            </Link>
          }
        />
      </section>
    </div>
  );
}
