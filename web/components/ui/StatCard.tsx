import Link from "next/link";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export interface StatCardProps {
  label: string;
  /** `null` means "no data" — rendered as an em dash, never as 0. */
  value: number | string | null;
  hint?: ReactNode;
  /** Click-through to the records behind the number (Phase 9 acceptance). */
  href?: string;
  /** `lg` for headline numbers on the dashboard. */
  size?: "default" | "lg";
  /** `accent` highlights the one number that needs attention. */
  tone?: "default" | "accent";
  className?: string;
}

const numberFormat = new Intl.NumberFormat("en-US");

export function StatCard({ label, value, hint, href, size = "default", tone = "default", className }: StatCardProps) {
  const display = value === null ? "—" : typeof value === "number" ? numberFormat.format(value) : value;
  const lg = size === "lg";
  const accent = tone === "accent";
  const body = (
    <>
      <div
        className={cn(
          "text-[11px] font-semibold",
          lg ? "font-mono" : "uppercase tracking-[0.06em]",
          accent ? "text-on-accent/85" : "text-ink-3",
        )}
      >
        {label}
      </div>
      <div
        className={cn(
          "tabular-nums",
          lg ? "text-[40px] font-extrabold leading-none tracking-[-0.04em]" : "text-[22px] font-semibold leading-tight tracking-tight",
          value === null && !accent && "text-ink-3",
        )}
      >
        {display}
      </div>
      {hint ? <div className={cn("text-xs", accent ? "text-on-accent/85" : "text-ink-2")}>{hint}</div> : null}
    </>
  );
  const base = cn(
    "flex min-w-0 flex-col border",
    lg ? "gap-4 rounded-2xl px-5 py-4" : "gap-1.5 rounded-lg px-3.5 py-3",
    accent ? "border-accent bg-accent text-on-accent" : "border-line bg-canvas",
    className,
  );
  if (href) {
    return (
      <Link
        href={href}
        className={cn(base, "transition-colors", accent ? "hover:opacity-90" : "hover:border-line-strong hover:bg-subtle")}
      >
        {body}
      </Link>
    );
  }
  return <div className={base}>{body}</div>;
}
