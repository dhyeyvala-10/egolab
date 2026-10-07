import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PipelineStairs } from "@/components/landing/PipelineStairs";
import { PipelineLevels } from "@/components/overview/PipelineLevels";
import { RecentJobs } from "@/components/overview/RecentJobs";
import type { JobSummary } from "@/lib/api/types";
import type { NavPage } from "@/lib/nav";
import { levelStatus, phaseLabel, PIPELINE } from "@/lib/pipeline";
import { pipelineCounts } from "@/lib/pipelineCounts";

afterEach(() => {
  vi.unstubAllGlobals();
});

const page = (phase: NavPage["phase"], built?: boolean): NavPage => ({ label: "x", href: `/${phase}`, phase, summary: "", built });

describe("pipeline levels", () => {
  it("lists the levels of the current plan, from raw video to export", () => {
    expect(PIPELINE.map((l) => l.name)).toEqual([
      "Raw Video",
      "Ingestion",
      "Processing",
      "Hand & Finger Tracking",
      "Movement Detection",
      "Human Annotation",
      "Dataset Versioning",
      "Export",
    ]); // Evaluation & Monitoring (Phases 8 & 9) is outside the plan, so it isn't shown
  });

  it("derives status and phases from the pages that do the work", () => {
    expect(levelStatus([page(3, true), page(3, true)])).toBe("live");
    expect(levelStatus([page(2, true), page(5)])).toBe("in_progress");
    expect(levelStatus([page(6)])).toBe("planned");
    expect(phaseLabel([page(3), page(3)])).toBe("Phase 3");
    expect(phaseLabel([page(5), page(2)])).toBe("Phases 2 & 5");
    expect(phaseLabel([page(9), page(2), page(5)])).toBe("Phases 2, 5 & 9");

    const annotation = PIPELINE.find((l) => l.name === "Human Annotation")!;
    expect(annotation.status).toBe("live");
    expect(annotation.phases).toBe("Phases 2 & 5");
    expect(PIPELINE.find((l) => l.name === "Dataset Versioning")!.status).toBe("live");
    const processing = PIPELINE.find((l) => l.name === "Processing")!;
    expect(processing.pages.map((p) => p.href)).toEqual(["/data/videos", "/pipelines/runs"]);
    expect(processing.status).toBe("live");
    expect(processing.phases).toBe("Phases 1 & 7");
    expect(PIPELINE.every((l) => l.status === "live")).toBe(true);
  });
});

describe("PipelineStairs", () => {
  it("shows the picked level and steps through them with the arrows", async () => {
    render(<PipelineStairs initial={0} />);
    const steps = screen.getByRole("list", { name: "Pipeline levels" });
    expect(within(steps).getByRole("button", { pressed: true })).toHaveTextContent("Raw Video");
    expect(screen.getByRole("heading", { level: 3 })).toHaveTextContent("Raw Video");

    await userEvent.click(within(steps).getByRole("button", { name: /Export/ }));
    expect(screen.getByRole("heading", { level: 3 })).toHaveTextContent("Export");
    expect(screen.getByText("Live")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Exports" })).toHaveAttribute("href", "/datasets/exports");

    await userEvent.click(screen.getByRole("button", { name: "Next level" }));
    expect(screen.getByRole("heading", { level: 3 })).toHaveTextContent("Raw Video"); // wraps around
    await userEvent.click(screen.getByRole("button", { name: "Previous level" }));
    expect(screen.getByRole("heading", { level: 3 })).toHaveTextContent("Export");
  });
});

describe("PipelineLevels", () => {
  it("shows each level's count by name, never inventing a zero", () => {
    const counts = Object.fromEntries(PIPELINE.map((l, i) => [l.name, { value: i === 1 ? null : 1000 + i, caption: `c${i}` }]));
    render(<PipelineLevels counts={counts} />);
    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(8);
    expect(links[0]).toHaveTextContent("1,000");
    expect(links[0]).toHaveAttribute("href", "/data/upload");
    expect(links[1]).toHaveTextContent("—"); // the count failed to load
    expect(links[6]).toHaveTextContent("1,006");
    expect(links[7]).toHaveTextContent("1,007");
    expect(links[7]).toHaveTextContent("Export");
  });

  it("shows a dash for a level with no count", () => {
    render(<PipelineLevels counts={{}} />);
    expect(screen.getAllByRole("link")[2]).toHaveTextContent("—");
  });
});

const job = (id: string, status: JobSummary["status"], error: string | null = null): JobSummary => ({
  id: `${id}0000000-0000-0000-0000-000000000000`,
  type: `job.${id}`,
  status,
  error,
  created_at: "2026-09-24T10:55:00Z",
  started_at: null,
  finished_at: null,
});

describe("RecentJobs", () => {
  it("filters by status and shows each filter's count", async () => {
    render(<RecentJobs jobs={[job("a", "running"), job("b", "failed", "ffmpeg exited with code 1"), job("c", "succeeded"), job("d", "queued")]} />);
    expect(screen.getAllByRole("listitem")).toHaveLength(4);
    expect(screen.getByRole("button", { name: /Active/ })).toHaveTextContent("2");

    await userEvent.click(screen.getByRole("button", { name: /Failed/ }));
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(1);
    expect(items[0]).toHaveTextContent("ffmpeg exited with code 1");
    expect(screen.getByRole("button", { name: /Failed/ })).toHaveAttribute("aria-pressed", "true");
  });

  it("says when a filter matches nothing", async () => {
    render(<RecentJobs jobs={[job("a", "running")]} />);
    await userEvent.click(screen.getByRole("button", { name: /Succeeded/ }));
    expect(screen.getByText("No jobs with this status")).toBeInTheDocument();
  });
});

describe("pipelineCounts", () => {
  it("reads each level's total from the list endpoints", async () => {
    const totals: Record<string, number> = {
      "/api/v1/uploads": 12,
      "/api/v1/videos": 11,
      "/api/v1/videos?status=ready": 9,
      "/api/v1/cv/runs": 7,
      "/api/v1/movement/events": 100,
      "/api/v1/movement/events?status=auto_detected": 60,
      "/api/v1/movement/events?status=needs_review": 15,
      "/api/v1/datasets/versions?status=ready": 3,
      "/api/v1/datasets/exports?status=ready": 5,
    };
    const fetchMock = vi.fn(async (input: string) => {
      const url = new URL(input);
      const status = /\/(events|videos|versions|exports)$/.test(url.pathname) ? url.searchParams.get("status") : null;
      const key = status ? `${url.pathname}?status=${status}` : url.pathname;
      expect(url.searchParams.get("limit")).toBe("1");
      return new Response(JSON.stringify({ items: [], total: totals[key], limit: 1, offset: 0 }), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);

    const counts = await pipelineCounts("tok");
    expect(PIPELINE.map((l) => counts[l.name].value)).toEqual([12, 11, 9, 7, 100, 25, 3, 5]);
    const urls = fetchMock.mock.calls.map(([u]) => String(u));
    expect(urls.some((u) => u.includes("/api/v1/videos?limit=1&status=ready"))).toBe(true);
    expect(urls.some((u) => u.includes("kind=hand_tracking") && u.includes("status=succeeded"))).toBe(true);
  });

  it("leaves a count blank when its request fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 500 })));
    const counts = await pipelineCounts("tok");
    expect(Object.values(counts).every((c) => c.value === null)).toBe(true);
  });
});
