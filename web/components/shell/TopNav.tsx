import Link from "next/link";
import { cn } from "@/lib/cn";
import { isActive, NAV, type NavSection } from "@/lib/nav";

export function activeSection(pathname: string): NavSection | undefined {
  return NAV.find((section) => section.pages.some((p) => isActive(p.href, pathname)));
}

/** Section pills for the top bar. Each opens its section's first page. */
export function SectionNav({ pathname, className }: { pathname: string; className?: string }) {
  const current = activeSection(pathname);
  return (
    <nav aria-label="Sections" className={cn("rounded-full border border-line bg-canvas p-1", className)}>
      <ul className="flex items-center gap-0.5">
        {NAV.map((section) => {
          const active = section === current;
          const single = section.pages.length === 1;
          return (
            <li key={section.id}>
              <Link
                href={section.pages[0].href}
                aria-current={active ? (single ? "page" : "true") : undefined}
                title={section.short ? section.label : undefined}
                className={cn(
                  "flex h-8 items-center whitespace-nowrap rounded-full px-3 font-semibold",
                  active ? "bg-ink text-ground" : "text-ink-2 hover:bg-hover hover:text-ink",
                )}
              >
                {section.short ?? section.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

/** Tabs for the pages of the current section, under the top bar. Hidden for one-page sections. */
export function PageTabs({ pathname }: { pathname: string }) {
  const section = activeSection(pathname);
  if (!section || section.pages.length < 2) return null;
  return (
    <nav aria-label={section.label} className="overflow-x-auto">
      <ul className="flex items-center gap-1">
        {section.pages.map((page) => {
          const active = isActive(page.href, pathname);
          return (
            <li key={page.href}>
              <Link
                href={page.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex h-8 items-center gap-1.5 whitespace-nowrap rounded-full border px-3",
                  active ? "border-line bg-canvas font-semibold text-ink" : "border-transparent text-ink-2 hover:bg-hover hover:text-ink",
                )}
              >
                {page.label}
                {page.built ? null : (
                  <span className="font-mono text-[10px] text-ink-3" title={`Not yet built — Phase ${page.phase}`}>
                    P{page.phase}
                  </span>
                )}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
