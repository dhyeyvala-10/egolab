import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Canvas } from "@/components/pipelines/Canvas";
import { ConfigForm } from "@/components/pipelines/ConfigForm";
import { PipelineBuilder } from "@/components/pipelines/PipelineBuilder";
import { RunView } from "@/components/pipelines/RunView";
import { Schedules } from "@/components/pipelines/Schedules";
import type { PipelineDetail, RunDetail, StepRead, StepTypeRead } from "@/lib/api/types";
import { autoLayout, completeLayout, overall, resultLinks, uniqueId, type PipelineGraph } from "@/lib/pipelines";

const push = vi.fn();
const replace = vi.fn();
const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace, refresh }) }));

afterEach(() => {
  vi.unstubAllGlobals();
  push.mockReset();
  replace.mockReset();
});

const schema = (properties: Record<string, unknown>, defs: Record<string, unknown> = {}) => ({ type: "object", properties, $defs: defs });
const step = (key: string, label: string, extra: Partial<StepTypeRead> = {}): StepTypeRead => ({
  key, label, category: "Tracking", per_video: true, description: `${label} does its thing`, requires: [], uses: [],
  defaults: {}, config_schema: schema({}), ...extra,
});
const STEPS: StepTypeRead[] = [
  step("ingest", "Ingest check", { category: "Ingest", defaults: { verify_checksum: false },
    config_schema: schema({ verify_checksum: { type: "boolean", default: false, description: "Re-hash the raw file" } }) }),
  step("hand_tracking", "Hand tracking", { defaults: { stride: 1 }, config_schema: schema({ stride: { type: "integer", minimum: 1, maximum: 30, default: 1 } }) }),
  step("finger_tracking", "Finger tracking", { requires: ["hand_tracking"] }),
  step("export", "Export", { category: "Dataset", per_video: false }),
];

const graph: PipelineGraph = {
  nodes: [
    { id: "ingest", type: "ingest", config: {}, retries: 0 },
    { id: "hands", type: "hand_tracking", config: {}, retries: 1 },
    { id: "fingers", type: "finger_tracking", config: {}, retries: 0 },
  ],
  edges: [{ from: "ingest", to: "hands" }, { from: "hands", to: "fingers" }],
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

describe("pipeline helpers", () => {
  it("lays steps out in columns by depth and places new ones below", () => {
    const layout = autoLayout(graph, STEPS.map((s) => s.key));
    expect(layout.ingest.x).toBeLessThan(layout.hands.x);
    expect(layout.hands.x).toBeLessThan(layout.fingers.x);
    expect(layout.ingest.y).toBe(layout.hands.y);
    const more = { ...graph, nodes: [...graph.nodes, { id: "export", type: "export", config: {}, retries: 0 }] };
    const complete = completeLayout(more, layout);
    expect(complete.export.y).toBeGreaterThan(layout.fingers.y);
    expect(uniqueId("quality_blur", new Set(["blur"]))).toBe("blur-2");
    expect(overall({ succeeded: 3, failed: 1 })).toBe("failed");
    expect(overall({ succeeded: 3, skipped: 1 })).toBe("succeeded");
    expect(overall({})).toBe("empty");
    expect(resultLinks("hand_tracking", { cv_run_id: "r1" })).toEqual([{ label: "Hand run", href: "/cv/hands/r1" }]);
    expect(resultLinks("dataset_build", { dataset_version_id: "v1", number: 3 })).toEqual([{ label: "v3", href: "/datasets/versions/v1" }]);
  });
});

describe("ConfigForm", () => {
  it("edits booleans, bounded numbers, enum lists, nested objects, and optional values from the schema", async () => {
    const onChange = vi.fn();
    const s = schema({
      verify: { type: "boolean", default: false },
      threshold: { type: "number", minimum: 0, maximum: 255, default: 50, description: "Mean brightness" },
      formats: { type: "array", items: { $ref: "#/$defs/ExportFormat" }, default: ["egolabs"] },
      split: { $ref: "#/$defs/Split" },
      min_confidence: { anyOf: [{ type: "number" }, { type: "null" }], default: null },
    }, {
      ExportFormat: { type: "string", enum: ["coco", "jsonl", "egolabs"] },
      Split: { type: "object", properties: { train: { type: "number", default: 0.8 }, group_by: { type: "string", enum: ["session", "video"] } } },
    });
    const value = { verify: false, threshold: 50, formats: ["egolabs"], split: { train: 0.8, group_by: "session" }, min_confidence: null };
    render(<ConfigForm schema={s} value={value} onChange={onChange} />);
    await userEvent.click(screen.getByLabelText("Verify"));
    expect(onChange).toHaveBeenLastCalledWith({ ...value, verify: true });
    const threshold = screen.getByLabelText("Threshold");
    expect(threshold).toHaveAttribute("max", "255");
    expect(screen.getByText("Mean brightness")).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("coco"));
    expect(onChange).toHaveBeenLastCalledWith({ ...value, formats: ["egolabs", "coco"] });
    fireEvent.change(screen.getByLabelText("Group by"), { target: { value: "video" } });
    expect(onChange).toHaveBeenLastCalledWith({ ...value, split: { train: 0.8, group_by: "video" } });
    expect(screen.getByLabelText("Min confidence")).toHaveAttribute("placeholder", "Not set");
  });
});

describe("Canvas", () => {
  it("draws steps and links, selects a step, and shows run status", async () => {
    const onSelect = vi.fn();
    const info = Object.fromEntries(STEPS.map((s) => [s.key, { label: s.label, category: s.category, perVideo: s.per_video }]));
    render(<Canvas graph={graph} layout={autoLayout(graph)} info={info} onSelect={onSelect}
                   status={{ hands: { tone: "error", text: "1/2 videos · 1 failed" } }} />);
    await userEvent.click(screen.getByRole("button", { name: /Hand tracking \(hands\): 1\/2 videos · 1 failed/ }));
    expect(onSelect).toHaveBeenCalledWith("hands");
    expect(screen.getByText("1/2 videos · 1 failed")).toBeInTheDocument();
    expect(screen.getAllByText("per video")).toHaveLength(3);
  });
});

describe("PipelineBuilder", () => {
  it("adds steps after the selected one, links them, checks the graph, and creates the pipeline", async () => {
    const calls: { path: string; body: unknown }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: string, init?: RequestInit) => {
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ path: input, body });
      if (input.includes("/pipelines/validate")) {
        const g = body as PipelineGraph;
        const fingers = g.nodes.find((n) => n.type === "finger_tracking");
        const ok = !fingers || g.edges.some((e) => e.to === fingers.id);
        return json({ ok, errors: ok ? [] : [{ node_id: fingers!.id, message: "Finger tracking needs Hand tracking before it" }], graph: ok ? g : null });
      }
      return json({ id: "p1", latest_version: 1 }, 201);
    }));
    render(<PipelineBuilder steps={STEPS} pipelines={[]} pipeline={null} sessions={[]} datasets={[]} canEdit />);
    const palette = screen.getByRole("complementary", { name: "Steps" });
    await userEvent.click(within(palette).getByRole("button", { name: /Hand tracking/ }));
    // "hands" is selected, so the next step runs after it
    await userEvent.click(within(palette).getByRole("button", { name: /Finger tracking/ }));
    await waitFor(() => expect(screen.getByTestId("graph-check")).toHaveTextContent("Valid: 2 steps, 1 links"));
    expect(within(palette).getByRole("button", { name: /Finger tracking/ })).toBeDisabled(); // each step once

    // Unlink it in the step panel: the API reports the missing requirement.
    const inspector = screen.getByRole("complementary", { name: "Selected step" });
    await userEvent.click(within(inspector).getByRole("checkbox", { name: /Hand tracking/ }));
    await waitFor(() => expect(screen.getByTestId("graph-check")).toHaveTextContent("finger-tracking: Finger tracking needs Hand tracking before it"));
    await userEvent.click(within(inspector).getByRole("checkbox", { name: /Hand tracking/ }));
    await waitFor(() => expect(screen.getByTestId("graph-check")).toHaveTextContent("Valid"));

    await userEvent.type(screen.getByLabelText("Name"), "Tracking");
    await userEvent.click(screen.getByRole("checkbox", { name: "Save as a template" }));
    await userEvent.click(screen.getByRole("button", { name: "Create pipeline" }));
    const created = calls.find((c) => c.path === "/api/v1/pipelines")!;
    expect(created.body).toMatchObject({
      name: "Tracking",
      is_template: true,
      graph: { nodes: [{ id: "hand-tracking", type: "hand_tracking", config: { stride: 1 } }, { id: "finger-tracking", type: "finger_tracking" }],
               edges: [{ from: "hand-tracking", to: "finger-tracking" }] },
    });
    expect(Object.keys((created.body as { layout: object }).layout)).toEqual(["hand-tracking", "finger-tracking"]);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/pipelines/builder?id=p1"));
  });

  it("saves an existing pipeline as a template without making a new version", async () => {
    const detail: PipelineDetail = {
      id: "p1", name: "Process", description: null, is_template: false, run_on_upload: false, latest_version: 2, step_count: 3, run_count: 0,
      last_run: null, schedule_count: 0, created_at: "2026-09-24T10:00:00Z", updated_at: "2026-09-24T10:00:00Z",
      layout: autoLayout(graph, STEPS.map((s) => s.key)),
      version: { id: "v2", number: 2, note: null, created_at: "2026-09-24T10:00:00Z", graph: graph as unknown as PipelineDetail["version"]["graph"],
                 graph_hash: "h", parent_version_id: "v1" },
      versions: [],
    };
    const puts: unknown[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: string, init?: RequestInit) => {
      if (input.includes("/pipelines/validate")) return json({ ok: true, errors: [], graph });
      puts.push(JSON.parse(String(init?.body)));
      return json({ ...detail, is_template: true, run_on_upload: true });
    }));
    const view = render(<PipelineBuilder steps={STEPS} pipelines={[detail]} pipeline={detail} sessions={[]} datasets={[]} canEdit />);
    const save = screen.getByRole("button", { name: "Save" });
    expect(save).toBeDisabled(); // nothing changed yet
    await userEvent.click(screen.getByRole("checkbox", { name: "Save as a template" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "Run automatically on new uploads" }));
    await userEvent.click(save);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Saved (steps unchanged, still version 2)"));
    expect(puts).toHaveLength(1);
    expect(puts[0]).toMatchObject({ name: "Process", is_template: true, run_on_upload: true, graph });

    // The page refreshes with the saved pipeline: the editor starts over from it, and the message stays.
    fireEvent.click(screen.getByRole("button", { name: "Hand tracking (hands)" }));
    const inspector = screen.getByRole("complementary", { name: "Selected step" });
    expect(within(inspector).getByRole("heading", { name: "Hand tracking" })).toBeInTheDocument();
    const refreshed = { ...detail, is_template: true, run_on_upload: true, updated_at: "2026-09-24T10:05:00Z" };
    view.rerender(<PipelineBuilder steps={STEPS} pipelines={[refreshed]} pipeline={refreshed} sessions={[]} datasets={[]} canEdit />);
    expect(within(screen.getByRole("complementary", { name: "Selected step" })).queryByRole("heading")).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("Saved (steps unchanged, still version 2)");
    expect(screen.getByRole("checkbox", { name: "Save as a template" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Run automatically on new uploads" })).toBeChecked();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });
});

const stepRow = (over: Partial<StepRead>): StepRead => ({
  id: "s1", run_id: "r1", node_id: "hands", step_type: "hand_tracking", label: "Hand tracking", video: { id: "v1", name: "grasp.mp4" },
  status: "succeeded", attempts: 1, max_attempts: 2, error: null, error_kind: null, error_label: null, retry_at: null,
  started_at: "2026-09-24T10:00:00Z", finished_at: "2026-09-24T10:00:04Z", duration_s: 4, result: {}, job_id: "j1",
  attempt_list: [{ id: "a1", number: 1, status: "succeeded", reason: "first", job_id: "j1", error: null, error_kind: null,
                   started_at: "2026-09-24T10:00:00Z", finished_at: "2026-09-24T10:00:04Z", created_at: "2026-09-24T10:00:00Z" }],
  ...over,
});

const run: RunDetail = {
  id: "r1", number: 3, pipeline: { id: "p1", name: "Process" }, version: 2, status: "failed", trigger: "manual", schedule_id: null,
  video_count: 2, inputs_label: "1 session", counts: { succeeded: 3, failed: 1 }, created_at: "2026-09-24T10:00:00Z",
  started_at: "2026-09-24T10:00:00Z", finished_at: "2026-09-24T10:01:00Z", duration_s: 60, error: "1 step failed; 1 waiting on them",
  created_by: { id: "u1", name: "Ada" }, job_id: "jr", graph: graph as unknown as RunDetail["graph"], layout: {}, inputs: {},
  nodes: [
    { node_id: "ingest", step_type: "ingest", label: "Ingest check", per_video: true, counts: { succeeded: 2 }, attempts: 2, seconds: 1 },
    { node_id: "hands", step_type: "hand_tracking", label: "Hand tracking", per_video: true, counts: { succeeded: 1, failed: 1 }, attempts: 2, seconds: 8 },
    { node_id: "fingers", step_type: "finger_tracking", label: "Finger tracking", per_video: true, counts: { pending: 1, succeeded: 1 }, attempts: 1, seconds: 1 },
  ],
};

describe("RunView", () => {
  it("retries one failed step, shows its attempts, and searches the logs", async () => {
    const failed = stepRow({
      id: "s2", video: { id: "v2", name: "tap.mp4" }, status: "failed", error: "EndpointConnectionError: storage down",
      error_kind: "storage_unreachable", error_label: "Storage or network unreachable",
      attempt_list: [{ id: "a2", number: 1, status: "failed", reason: "first", job_id: "j2", error: "storage down", error_kind: "storage_unreachable",
                       started_at: "2026-09-24T10:00:00Z", finished_at: "2026-09-24T10:00:01Z", created_at: "2026-09-24T10:00:00Z" }],
    });
    const done = stepRow({ result: { cv_run_id: "cv1" } });
    const posted: { path: string; body: unknown }[] = [];
    const logQueries: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        posted.push({ path: input, body: JSON.parse(String(init.body)) });
        return json({ retried: 1, steps: [] });
      }
      if (input.includes("/logs")) {
        logQueries.push(input);
        return json({ items: [{ id: 1, ts: "2026-09-24T10:00:01Z", level: "error", message: "Step failed (Storage or network unreachable): storage down",
          data: { error_kind: "storage_unreachable" }, job_id: "j2", source: "Hand tracking", node_id: "hands", step_run_id: "s2", attempt: 1,
          video: { id: "v2", name: "tap.mp4" } }], next_after_id: null, matched: 1, total: 42 });
      }
      if (input.includes("/steps")) return json({ items: [done, failed], total: 2, limit: 500, offset: 0 });
      return json(run);
    }));
    render(<RunView initial={run} initialSteps={{ items: [done, failed], total: 2, limit: 500, offset: 0 }} steps={STEPS} canEdit />);

    expect(screen.getByRole("button", { name: "Retry 1 failed step" })).toBeInTheDocument();
    const rows = screen.getAllByRole("row");
    const failedRow = rows.find((r) => r.getAttribute("data-step") === "s2")!;
    expect(failedRow).toHaveTextContent("Storage or network unreachable: EndpointConnectionError: storage down");
    expect(rows.find((r) => r.getAttribute("data-step") === "s1")).toHaveTextContent("Hand run");
    await userEvent.click(within(failedRow).getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(posted).toEqual([{ path: "/api/v1/pipelines/runs/r1/retry", body: { step_ids: ["s2"] } }]));

    await userEvent.click(within(failedRow).getByRole("button", { name: /Hand tracking/ }));
    expect(screen.getByText("Attempt 1")).toBeInTheDocument();

    await waitFor(() => expect(screen.getByTestId("log-meta")).toHaveTextContent("1 of 42 lines match"));
    await userEvent.type(screen.getByLabelText("Search the logs"), "storage down");
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() => expect(logQueries.some((u) => u.includes("q=storage+down"))).toBe(true));
    await userEvent.click(within(failedRow).getByRole("button", { name: "Logs" }));
    await waitFor(() => expect(logQueries.some((u) => u.includes("step_run_id=s2"))).toBe(true));
    expect(screen.getByTestId("log-lines")).toHaveTextContent("[Hand tracking #1 · tap.mp4]");
  });
});

describe("Schedules", () => {
  it("previews a cron preset's next times before creating the schedule", async () => {
    const bodies: unknown[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: string, init?: RequestInit) => {
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      if (input.includes("/preview")) {
        bodies.push(body);
        return json({ ok: true, error: null, upcoming: ["2026-09-25T02:00:00Z", "2026-09-26T02:00:00Z"] });
      }
      return json({}, 201);
    }));
    render(<Schedules schedules={[]} pipelines={[{ id: "p1", name: "Process", description: null, is_template: false, run_on_upload: false, latest_version: 2, step_count: 3,
      run_count: 0, last_run: null, schedule_count: 0, created_at: "", updated_at: "" }]} sessions={[{ id: "s1", name: "SESSION_1" }]} datasets={[]} canEdit />);
    await userEvent.click(screen.getByRole("button", { name: "Every hour" }));
    await waitFor(() => expect(bodies.at(-1)).toEqual({ cron: "0 * * * *", timezone: "UTC" }));
    await waitFor(() => expect(screen.getByTestId("cron-preview")).toHaveTextContent("Next: 25 Sept 2026"));
    const create = screen.getByRole("button", { name: "Create schedule" });
    expect(create).toBeDisabled(); // nothing selected to run on
    await userEvent.click(screen.getByRole("checkbox", { name: /SESSION_1/ }));
    expect(create).toBeEnabled();
  });
});
