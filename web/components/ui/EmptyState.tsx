import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export interface EmptyStateProps {
  title: string;
  description?: ReactNode;
  icon?: ReactNode;
  action?: ReactNode;
  /** `compact` for use inside tables and small panels. */
  size?: "default" | "compact";
  className?: string;
}

export function EmptyState({ title, description, icon, action, size = "default", className }: EmptyStateProps) {
  return (
    <div
      role="status"
      className={cn(
        "flex flex-col items-center justify-center text-center",
        size === "compact" ? "gap-1 px-4 py-6" : "gap-2 px-6 py-12",
        className,
      )}
    >
      {icon ? <div className="mb-1 text-ink-3">{icon}</div> : null}
      <div className={cn("font-semibold", size === "compact" ? "text-[13px]" : "text-sm")}>{title}</div>
      {description ? <div className="max-w-[52ch] text-ink-2">{description}</div> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}
