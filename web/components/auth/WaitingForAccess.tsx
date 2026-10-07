import { Hourglass, LogOut, RotateCw } from "lucide-react";
import Link from "next/link";
import { EmptyState } from "@/components/ui";
import type { UserRead } from "@/lib/api/types";
import { logout } from "@/lib/auth/actions";

/** Shown instead of the app to someone signed in whom the admin hasn't given access yet. */
export function WaitingForAccess({ user }: { user: UserRead }) {
  return (
    <div className="grid min-h-full place-items-center px-4 py-10">
      <div className="w-full max-w-[520px] rounded-lg border border-line bg-canvas">
        <EmptyState
          icon={<Hourglass className="size-5 text-warning" aria-hidden />}
          title="Waiting for access"
          description={
            <>
              <span className="block">
                You&apos;re signed in as <strong className="text-ink">{user.email}</strong>, but the admin hasn&apos;t given this
                account access yet.
              </span>
              <span className="mt-2 block">Ask them to open Settings → Users and give you a role, then check again.</span>
            </>
          }
          action={
            <div className="flex flex-wrap justify-center gap-2">
              <Link href="/dashboard" className="inline-flex h-9 items-center gap-1.5 rounded-md bg-ink px-3 text-sm font-semibold text-ground hover:opacity-90">
                <RotateCw className="size-3.5" aria-hidden /> Check again
              </Link>
              <form action={logout}>
                <button type="submit" className="inline-flex h-9 items-center gap-1.5 rounded-md border border-line px-3 text-sm font-semibold hover:bg-hover">
                  <LogOut className="size-3.5" aria-hidden /> Sign out
                </button>
              </form>
            </div>
          }
        />
      </div>
    </div>
  );
}
