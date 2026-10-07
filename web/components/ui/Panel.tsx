import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export function Panel({ title, hint, actions, children, className, bodyClassName }: {
  title: string;
  hint?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={cn("min-w-0 rounded-lg border border-line bg-canvas", className)}>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3.5 py-2.5">
        <h2 className="text-[13px] font-semibold">{title}</h2>
        {hint ? <span className="text-xs text-ink-3">{hint}</span> : null}
        {actions}
      </div>
      <div className={cn("px-3.5 py-2", bodyClassName)}>{children}</div>
    </section>
  );
}
