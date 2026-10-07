import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { LineageView, layout, pathToRaw } from "@/components/datasets/LineageView";
import { SplitBar } from "@/components/datasets/SplitBar";
import type { LineageGraph } from "@/lib/api/types";
import { defaultSpec, describeFilters, fullCounts, fullSpec, shortHash } from "@/lib/datasets";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }) }));

const node = (id: string, type: string, label: string, detail: Record<string, unknown> = {}) =>
  ({ id, type, label, detail, href: null }) as LineageGraph["nodes"][number];

const graph: LineageGraph = {
  root: "sample:1",
  reaches_raw_file: true,
  nodes: [
    node("sample:1", "sample", "Sample #0 · grasp"),
    node("dataset_version:1", "dataset_version", "Grasps v1"),
    node("event:1", "event", "Movement event · grasp"),
    node("cv_run:1", "cv_run", "Movement classification run", { kind: "movement" }),
    node("cv_run:2", "cv_run", "Hand tracking run", { kind: "hand_tracking" }),
    node("video:1", "video", "grasp.mp4"),
    node("raw_file:abc", "raw_file", "abc.mp4", { sha256: "abc", storage_key: "raw/abc.mp4" }),
  ],
  edges: [
    { source: "sample:1", target: "dataset_version:1", relation: "member_of" },
    { source: "sample:1", target: "event:1", relation: "from_event" },
    { source: "event:1", target: "cv_run:1", relation: "classified_by" },
    { source: "event:1", target: "cv_run:2", relation: "keypoints_from" },
    { source: "cv_run:2", target: "video:1", relation: "input" },
    { source: "cv_run:1", target: "video:1", relation: "input" },
    { source: "video:1", target: "raw_file:abc", relation: "stored_as" },
  ],
};

describe("lineage view", () => {
  it("lays nodes out in columns by distance from the sample and finds the path to the raw file", () => {
    const { pos, depth } = layout(graph);
    expect(depth.get("sample:1")).toBe(0);
    expect(depth.get("event:1")).toBe(1);
    expect(depth.get("raw_file:abc")).toBe(4);
    expect(pos.get("cv_run:1")!.x).toBe(pos.get("cv_run:2")!.x);
    expect(pathToRaw(graph)).toEqual(["sample:1", "event:1", "cv_run:1", "video:1", "raw_file:abc"]);
    expect(pathToRaw({ ...graph, edges: graph.edges.slice(0, 4) })).toEqual([]);
    // A shortcut (sample → frames → raw file) is not preferred over the chain that produced the sample.
    const shortcut: LineageGraph = { ...graph, nodes: [...graph.nodes, node("frames:1", "frames", "Frames 10–40")],
      edges: [{ source: "sample:1", target: "frames:1", relation: "spans" }, { source: "frames:1", target: "raw_file:abc", relation: "decoded_from" }, ...graph.edges] };
    expect(pathToRaw(shortcut)).toEqual(["sample:1", "event:1", "cv_run:1", "video:1", "raw_file:abc"]);
  });

  it("says it reached the raw file, lists the path, and shows a node's record", () => {
    render(<LineageView graph={graph} />);
    expect(screen.getByTestId("reaches")).toHaveTextContent("Traced to the raw file");
    const path = screen.getByTestId("path");
    expect(path).toHaveTextContent("Sample: Sample #0 · grasp");
    expect(path).toHaveTextContent("Raw file: abc.mp4");
    // The raw file is selected first; its record shows the storage key and hash.
    expect(screen.getByTestId("node-detail")).toHaveTextContent("raw/abc.mp4");
    fireEvent.click(screen.getByRole("button", { name: "Model run: Hand tracking run" }));
    expect(screen.getByTestId("node-detail")).toHaveTextContent("hand_tracking");
    expect(screen.getByTestId("node-detail")).toHaveTextContent("keypoints from");
  });
});

describe("dataset helpers", () => {
  it("fills a partial spec and counts, and describes filters in words", () => {
    const spec = fullSpec({ filters: { classes: ["grasp"], statuses: ["confirmed"], human_verified_only: true }, split: { train: 0.8, val: 0.1, test: 0.1, group_by: "operator", seed: 4 } });
    expect(spec.filters.session_ids).toEqual([]);
    expect(spec.split.train).toBe(0.8);
    const words = describeFilters({ ...spec, filters: { ...spec.filters, session_ids: ["s1"] } }, { s1: "SESSION_2026_09_24_001" });
    expect(words).toContain("Review: Confirmed (by a person only)");
    expect(words).toContain("Sessions: SESSION_2026_09_24_001");
    expect(words).toContain("Classes: grasp");
    expect(words.at(-1)).toBe("Split 80/10/10 by operator, seed 4");
    expect(fullCounts(undefined).splits).toEqual({ train: 0, val: 0, test: 0 });
    expect(shortHash("a".repeat(64))).toBe("aaaaaaaaaaaa…");
    expect(defaultSpec().filters.statuses).toEqual(["confirmed"]);
  });

  it("draws the split bar with counts and groups", () => {
    render(<SplitBar counts={{ splits: { train: 8, val: 1, test: 1 }, groups: { train: 4, val: 1, test: 1 }, classes: {}, statuses: {}, sources: {}, videos: 3 }} />);
    expect(screen.getByRole("img", { name: "train 8, val 1, test 1" })).toBeInTheDocument();
    expect(screen.getByTestId("split-bar")).toHaveTextContent("8 · 4 groups");
  });
});
