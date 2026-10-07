"use client";

import {
  Box,
  Database,
  FlaskConical,
  Layers,
  LayoutDashboard,
  LogOut,
  PenTool,
  Radio,
  ScanEye,
  Server,
  Settings,
  Workflow,
  X,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import type { UserRead } from "@/lib/api/types";
import { logout } from "@/lib/auth/actions";
import { cn } from "@/lib/cn";
import { isActive, NAV, type NavSection, type SectionIcon } from "@/lib/nav";

const ICONS: Record<SectionIcon, LucideIcon> = {
  overview: LayoutDashboard,
  data: Database,
  annotation: PenTool,
  cv: ScanEye,
  pipelines: Workflow,
  datasets: Layers,
  models: Box,
  realtime: Radio,
  experiments: FlaskConical,
  infrastructure: Server,
  settings: Settings,
};

/** Full navigation list, shown in a drawer on screens too narrow for the top bar's section pills. */
export interface SidebarProps {
  pathname: string;
  /** Close button, and close after navigating. */
  onClose: () => void;
  /** Signed-in user. Omitted in isolated component tests. */
  user?: UserRead;
  apiUrl?: string;
}

function sectionActive(section: NavSection, pathname: string) {
  return section.pages.some((p) => isActive(p.href, pathname));
}

export function Sidebar({ pathname, onClose, user, apiUrl }: SidebarProps) {
  return (
    <div className="flex h-full flex-col bg-subtle">
      <div className="flex min-h-[52px] items-center gap-2.5 border-b border-line px-3 pl-4">
        <div className="grid size-[26px] flex-none place-items-center rounded-md bg-ink text-xs font-bold text-canvas">EL</div>
        <div className="min-w-0 leading-tight">
          <div className="text-sm font-bold tracking-tight">Ego Labs</div>
          <div className="text-[11px] text-ink-3">Egocentric data OS</div>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close navigation"
          className="ml-auto grid size-7 place-items-center rounded-md border border-line bg-canvas text-ink-2 hover:bg-hover hover:text-ink"
        >
          <X className="size-4" aria-hidden />
        </button>
      </div>

      <nav aria-label="Main" className="flex-1 overflow-y-auto px-2 py-2.5">
        <ul className="flex flex-col gap-0.5">
          {NAV.map((section) => {
            const Icon = ICONS[section.id];
            const active = sectionActive(section, pathname);

            if (section.pages.length === 1) {
              const page = section.pages[0];
              return (
                <li key={section.id}>
                  <NavLink href={page.href} active={active} onClick={onClose} phase={page.built ? undefined : page.phase}>
                    <Icon className="size-4 flex-none" aria-hidden />
                    <span className="truncate">{section.label}</span>
                  </NavLink>
                </li>
              );
            }

            return (
              <li key={section.id} className="mt-2 first:mt-0">
                <div className={cn("flex h-7 items-center gap-2 px-2 text-xs font-semibold text-ink-3", active && "text-ink")}>
                  <Icon className="size-4 flex-none" aria-hidden />
                  <span className="truncate">{section.label}</span>
                </div>
                <ul className="flex flex-col gap-0.5">
                  {section.pages.map((page) => (
                    <li key={page.href}>
                      <NavLink
                        href={page.href}
                        active={isActive(page.href, pathname)}
                        onClick={onClose}
                        phase={page.built ? undefined : page.phase}
                        indent
                      >
                        <span className="truncate">{page.label}</span>
                      </NavLink>
                    </li>
                  ))}
                </ul>
              </li>
            );
          })}
        </ul>
      </nav>

      {user ? <UserFooter user={user} apiUrl={apiUrl} /> : null}
    </div>
  );
}

function NavLink({
  href,
  active,
  onClick,
  phase,
  indent,
  children,
}: {
  href: string;
  active: boolean;
  onClick?: () => void;
  phase?: number;
  indent?: boolean;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      onClick={onClick}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex h-[30px] items-center gap-2 rounded-md pr-2 text-ink-2 hover:bg-hover hover:text-ink",
        indent ? "pl-8" : "pl-2",
        active && "bg-canvas font-semibold text-ink shadow-[inset_0_0_0_1px_var(--color-line)]",
      )}
    >
      {children}
      {phase != null ? (
        <span className="ml-auto font-mono text-[10px] text-ink-3" title={`Not yet built — Phase ${phase}`}>
          P{phase}
        </span>
      ) : null}
    </Link>
  );
}

function UserFooter({ user, apiUrl }: { user: UserRead; apiUrl?: string }) {
  const signOut = (
    <form action={logout}>
      <button
        type="submit"
        aria-label="Sign out"
        title="Sign out"
        className="grid size-7 flex-none place-items-center rounded-md text-ink-2 hover:bg-hover hover:text-ink"
      >
        <LogOut className="size-3.5" aria-hidden />
      </button>
    </form>
  );
  return (
    <div className="border-t border-line px-3 py-2.5 pl-4">
      <div className="flex items-center gap-2">
        <div className="min-w-0 flex-1 leading-tight">
          <div className="truncate text-xs font-semibold">{user.name || user.email}</div>
          <div className="truncate text-[11px] text-ink-3">
            <span className="capitalize">{user.role}</span>
            {user.name ? ` · ${user.email}` : ""}
          </div>
        </div>
        {signOut}
      </div>
      {apiUrl ? (
        <div className="mt-1.5 truncate text-[11px] text-ink-3" title={apiUrl}>
          API <span className="font-mono text-ink-2">{apiUrl}</span>
        </div>
      ) : null}
    </div>
  );
}
