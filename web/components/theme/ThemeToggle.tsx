"use client";

import { Moon, Sun } from "lucide-react";
import { useSyncExternalStore } from "react";
import { cn } from "@/lib/cn";
import { THEME_KEY, type Theme } from "@/lib/theme";

const listeners = new Set<() => void>();

function systemTheme(): Theme {
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function read(): Theme {
  const set = document.documentElement.getAttribute("data-theme");
  return set === "light" || set === "dark" ? set : systemTheme();
}

function subscribe(cb: () => void) {
  listeners.add(cb);
  const media = window.matchMedia?.("(prefers-color-scheme: dark)");
  media?.addEventListener("change", cb);
  return () => {
    listeners.delete(cb);
    media?.removeEventListener("change", cb);
  };
}

export function setTheme(theme: Theme) {
  document.documentElement.setAttribute("data-theme", theme);
  try {
    window.localStorage.setItem(THEME_KEY, theme);
  } catch {
    // storage unavailable: the choice lasts until reload
  }
  listeners.forEach((l) => l());
}

/** The theme in effect: the stored choice, else the system setting. Light on the server. */
export function useTheme(): [Theme, (theme: Theme) => void] {
  return [useSyncExternalStore(subscribe, read, () => "light"), setTheme];
}

/** `className` sets the size too (default `size-9`). */
export function ThemeToggle({ className = "size-9" }: { className?: string }) {
  const [theme, set] = useTheme();
  const next = theme === "dark" ? "light" : "dark";
  return (
    <button
      type="button"
      onClick={() => set(next)}
      aria-label={`Switch to ${next} mode`}
      title={`Switch to ${next} mode`}
      className={cn(
        "grid flex-none place-items-center rounded-full border border-line bg-canvas text-ink-2 hover:bg-hover hover:text-ink",
        className,
      )}
    >
      {theme === "dark" ? <Sun className="size-4" aria-hidden /> : <Moon className="size-4" aria-hidden />}
    </button>
  );
}
