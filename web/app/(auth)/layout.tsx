import Link from "next/link";
import type { ReactNode } from "react";
import { ThemeToggle } from "@/components/theme/ThemeToggle";

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="relative grid min-h-full place-items-center bg-ground px-4 py-10">
      <div className="absolute right-4 top-4">
        <ThemeToggle />
      </div>
      <div className="flex w-full max-w-[400px] flex-col gap-6">
        <Link href="/" className="flex items-center gap-2.5 self-center">
          <span className="grid size-9 place-items-center rounded-xl bg-ink text-sm font-extrabold text-ground">EL</span>
          <span className="leading-tight">
            <span className="block text-base font-bold tracking-tight">Ego Labs</span>
            <span className="block text-[11px] text-ink-3">Egocentric data OS</span>
          </span>
        </Link>
        <div className="rounded-2xl border border-line bg-canvas p-7 shadow-sm">{children}</div>
        <Link href="/" className="self-center text-xs text-ink-3 hover:text-ink">← Back to the home page</Link>
      </div>
    </div>
  );
}
