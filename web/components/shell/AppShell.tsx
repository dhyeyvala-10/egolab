"use client";

import { Menu } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";
import { ThemeToggle } from "@/components/theme/ThemeToggle";
import type { UserRead } from "@/lib/api/types";
import { initials } from "@/lib/format";
import { Sidebar } from "./Sidebar";
import { PageTabs, SectionNav } from "./TopNav";

export function AppShell({ children, user, apiUrl }: { children: ReactNode; user: UserRead; apiUrl?: string }) {
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div className="flex min-h-full flex-col">
      {/* Navigation drawer, below the width where the section pills fit */}
      {menuOpen ? (
        <div className="fixed inset-0 z-40 xl:hidden">
          <button
            type="button"
            aria-label="Close navigation"
            className="absolute inset-0 bg-black/30"
            onClick={() => setMenuOpen(false)}
          />
          <aside className="absolute inset-y-0 left-0 w-[272px] max-w-[85vw] border-r border-line shadow-xl">
            <Sidebar pathname={pathname} onClose={() => setMenuOpen(false)} user={user} apiUrl={apiUrl} />
          </aside>
        </div>
      ) : null}

      <header className="sticky top-0 z-30 border-b border-line bg-ground/95 backdrop-blur">
        <div className="flex h-16 items-center gap-3 px-4 md:px-7">
          <button
            type="button"
            onClick={() => setMenuOpen(true)}
            aria-label="Open navigation"
            className="grid size-9 place-items-center rounded-full border border-line bg-canvas text-ink-2 hover:bg-hover xl:hidden"
          >
            <Menu className="size-4" aria-hidden />
          </button>
          <Link href="/" className="flex flex-none items-center gap-2">
            <span className="grid size-7 place-items-center rounded-lg bg-ink text-xs font-extrabold text-ground">EL</span>
            <span className="text-sm font-bold tracking-tight">Ego Labs</span>
          </Link>
          <SectionNav pathname={pathname} className="mx-auto hidden xl:block" />
          <div className="ml-auto flex flex-none items-center gap-2 xl:ml-0">
            <ThemeToggle />
            <Link
              href="/profile"
              aria-label={`Your profile (${user.name || user.email})`}
              className="flex h-9 items-center gap-2 rounded-full border border-line bg-canvas pl-1 pr-1 hover:bg-hover 2xl:pr-3"
            >
              <span className="grid size-7 place-items-center rounded-full bg-accent text-[11px] font-extrabold text-on-accent">
                {initials(user.name || user.email)}
              </span>
              <span className="hidden max-w-[160px] truncate font-semibold 2xl:block">{user.name || user.email}</span>
            </Link>
          </div>
        </div>
        <div className="px-4 pb-2.5 empty:hidden md:px-7">
          <PageTabs pathname={pathname} />
        </div>
      </header>

      <main className="min-w-0 flex-1 px-4 pb-16 pt-6 md:px-7 *:mx-auto">{children}</main>
    </div>
  );
}
