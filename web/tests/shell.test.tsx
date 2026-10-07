import { act, render, renderHook, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Sidebar } from "@/components/shell/Sidebar";
import { activeSection, PageTabs, SectionNav } from "@/components/shell/TopNav";
import { ThemeToggle, useTheme } from "@/components/theme/ThemeToggle";
import { initials } from "@/lib/format";
import { ALL_PAGES, findPage, FULL_NAV, isActive, NAV, PLAN_LAST_PHASE } from "@/lib/nav";
import { THEME_KEY } from "@/lib/theme";

describe("nav config", () => {
  it("lists the sections of the current plan in order, keeping later phases for later", () => {
    expect(NAV.map((s) => s.label)).toEqual(["Overview", "Data", "Annotation", "Computer Vision", "Pipelines", "Datasets", "Settings"]);
    expect(FULL_NAV.map((s) => s.label)).toEqual([
      "Overview",
      "Data",
      "Annotation",
      "Computer Vision",
      "Pipelines",
      "Datasets",
      "Models",
      "Real-Time",
      "Experiments",
      "Infrastructure",
      "Settings",
    ]);
    expect(PLAN_LAST_PHASE).toBe(7);
    for (const p of ALL_PAGES) expect(p.built || p.phase <= PLAN_LAST_PHASE).toBe(true);
    expect(findPage("/models/evaluation")).toBeUndefined(); // Phase 8: not shown
  });

  it("has unique hrefs and valid phases", () => {
    const hrefs = ALL_PAGES.map((p) => p.href);
    expect(new Set(hrefs).size).toBe(hrefs.length);
    for (const p of ALL_PAGES) expect(p.phase).toBeGreaterThanOrEqual(0);
  });

  it("serves the Overview at /dashboard, leaving / to the landing page", () => {
    expect(findPage("/dashboard")?.label).toBe("Overview");
    expect(findPage("/")).toBeUndefined();
  });

  it("matches active routes by prefix", () => {
    expect(isActive("/dashboard", "/data/videos")).toBe(false);
    expect(isActive("/data/videos", "/data/videos/123")).toBe(true);
    expect(isActive("/data/videos", "/data/videos-archive")).toBe(false);
    expect(findPage("/data/sessions/")?.label).toBe("Sessions");
  });
});

describe("top bar", () => {
  it("marks the current section and opens each section at its first page", () => {
    render(<SectionNav pathname="/cv/movements/events/abc" />);
    const current = screen.getByRole("link", { current: true });
    expect(current).toHaveTextContent("Vision");
    expect(current).toHaveAttribute("href", "/cv/hands");
    expect(screen.getByRole("link", { name: "Pipelines" })).toHaveAttribute("href", "/pipelines/builder");
    expect(screen.queryByRole("link", { name: "Live" })).toBeNull(); // Phase 9: not in the plan
  });

  it("marks one-page sections as the current page", () => {
    render(<SectionNav pathname="/dashboard" />);
    expect(screen.getByRole("link", { current: "page" })).toHaveTextContent("Overview");
  });

  it("shows the current section's pages as tabs; built pages carry no phase tag", () => {
    render(<PageTabs pathname="/pipelines/builder" />);
    const tabs = screen.getByRole("navigation", { name: "Pipelines" });
    const current = within(tabs).getByRole("link", { current: "page" });
    expect(current).toHaveTextContent("Pipeline Builder");
    expect(within(tabs).getAllByRole("link").map((l) => l.textContent)).toEqual(["Pipeline Builder", "Runs", "Schedules", "Templates"]);
    render(<PageTabs pathname="/annotation/review" />);
    const annotation = screen.getByRole("navigation", { name: "Annotation" });
    expect(within(annotation).getByRole("link", { name: "Review" })).not.toHaveTextContent(/P\d/);
    expect(within(annotation).getByRole("link", { name: "Video Inspector" })).not.toHaveTextContent(/P\d/);
  });

  it("has no tabs for one-page sections or unknown paths", () => {
    const { container, rerender } = render(<PageTabs pathname="/dashboard" />);
    expect(container).toBeEmptyDOMElement();
    rerender(<PageTabs pathname="/profile" />);
    expect(container).toBeEmptyDOMElement();
    expect(activeSection("/profile")).toBeUndefined();
  });
});

describe("navigation drawer", () => {
  it("marks the current page, tags unbuilt pages, and closes after navigating", async () => {
    const onClose = vi.fn();
    render(<Sidebar pathname="/pipelines/runs/abc" onClose={onClose} />);
    const current = screen.getByRole("link", { current: "page" });
    expect(current).toHaveTextContent("Runs");
    expect(screen.getByRole("link", { name: "Overview" })).toHaveAttribute("href", "/dashboard");
    // built pages carry no phase tag; the one page of the plan still to build does
    for (const name of [/^Sessions/, /^Video Inspector/, /^Review/, /^Dataset Builder/, /^Pipeline Builder/, /^Schedules/]) {
      expect(screen.getByRole("link", { name })).not.toHaveTextContent(/P\d/);
    }
    // Settings is built now: the admin's Users, Requests, Limits, and Activity pages.
    for (const name of [/^Users/, /^Requests/, /^Limits/, /^Activity/]) {
      expect(screen.getByRole("link", { name })).not.toHaveTextContent(/P\d/);
    }
    expect(screen.queryByRole("link", { name: /^Model Registry/ })).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Close navigation" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe("theme", () => {
  it("switches between light and dark and remembers the choice", async () => {
    document.documentElement.removeAttribute("data-theme");
    render(<ThemeToggle />);
    await userEvent.click(screen.getByRole("button", { name: "Switch to dark mode" }));
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    expect(window.localStorage.getItem(THEME_KEY)).toBe("dark");

    await userEvent.click(screen.getByRole("button", { name: "Switch to light mode" }));
    expect(document.documentElement).toHaveAttribute("data-theme", "light");
    expect(window.localStorage.getItem(THEME_KEY)).toBe("light");
  });

  it("follows an attribute set before hydration", () => {
    document.documentElement.setAttribute("data-theme", "dark");
    const { result } = renderHook(() => useTheme());
    expect(result.current[0]).toBe("dark");
    act(() => result.current[1]("light"));
    expect(result.current[0]).toBe("light");
    document.documentElement.removeAttribute("data-theme");
  });
});

describe("initials", () => {
  it("takes the first and last word, or the start of an email", () => {
    expect(initials("Ada Lovelace")).toBe("AL");
    expect(initials("Grace Brewster Hopper")).toBe("GH");
    expect(initials("ada@example.com")).toBe("AD");
    expect(initials("ada.lovelace@example.com")).toBe("AL");
  });
});
