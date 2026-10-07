import Link from "next/link";
import { cn } from "@/lib/cn";
import { NAV, type SectionIcon } from "@/lib/nav";
import { LEVEL_STATUS_LABEL, levelStatus, phaseLabel } from "@/lib/pipeline";

const PLAIN = "border border-line bg-canvas";

/**
 * Tile look per section. The spans fill a four-column grid in NAV order with no gaps. `solid` tiles
 * carry their own text colour; the rest use the ink greys.
 */
const TILES: Partial<Record<SectionIcon, { className: string; solid?: boolean }>> = {
  data: { className: "lg:col-span-2 bg-ink text-ground", solid: true },
  annotation: { className: "bg-accent-soft" },
  cv: { className: "lg:row-span-2 bg-accent text-on-accent", solid: true },
  pipelines: { className: PLAIN },
  datasets: { className: "lg:col-span-2 bg-sage-soft" },
  models: { className: PLAIN },
  realtime: { className: PLAIN },
  experiments: { className: PLAIN },
  infrastructure: { className: "border border-dashed border-line-strong" },
};

const MODULES = NAV.filter((s) => s.id in TILES);

/** The app's sections as tiles, each with how far along it is. */
export function ModuleGrid() {
  return (
    <ul className="grid auto-rows-[minmax(180px,auto)] grid-cols-1 gap-3.5 sm:grid-cols-2 lg:grid-cols-4">
      {MODULES.map((section, i) => {
        const status = levelStatus(section.pages);
        const tile = TILES[section.id]!;
        return (
          <li key={section.id} className={cn("flex rounded-3xl", tile.className)}>
            <Link href={section.pages[0].href} className="flex w-full flex-col justify-between gap-6 rounded-3xl p-6 hover:opacity-90">
              <span className={cn("flex justify-between font-mono text-xs", tile.solid ? "opacity-80" : "text-ink-3")}>
                <span>{String(i + 1).padStart(2, "0")}</span>
                <span>{status === "planned" ? phaseLabel(section.pages) : LEVEL_STATUS_LABEL[status]}</span>
              </span>
              <span className="flex flex-col gap-1">
                <span className="text-2xl font-extrabold tracking-tight">{section.label}</span>
                <span className={cn("text-sm", tile.solid ? "opacity-85" : "text-ink-2")}>
                  {section.pages.map((p) => p.label).join(" · ")}
                </span>
              </span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
