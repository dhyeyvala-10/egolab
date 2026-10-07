import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ObjectOverlay } from "@/components/cv/ObjectOverlay";
import { EvidenceCharts } from "@/components/movement/EvidenceCharts";
import { InteractionGraphView } from "@/components/movement/InteractionGraphView";
import type { InteractionGraph } from "@/lib/api/types";
import { frameRuns, measurementUnit, thresholdFor } from "@/lib/cv/evidence";
import { layoutGraph, pathsThrough } from "@/lib/cv/graph";
import { createFrameStore } from "@/lib/inspector/frameStore";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }) }));

afterEach(() => vi.unstubAllGlobals());

const graph: InteractionGraph = {
  total_events: 3,
  nodes: [
    { id: "hand:right", kind: "hand", label: "Right hand", count: 3 },
    { id: "finger:index", kind: "finger", label: "Index", count: 2 },
    { id: "finger:whole_hand", kind: "finger", label: "Whole hand", count: 1 },
    { id: "movement:tap", kind: "movement", label: "Tap", count: 2 },
    { id: "movement:hand_enter", kind: "movement", label: "Hand enters frame", count: 1 },
    { id: "object:cup", kind: "object", label: "cup", count: 2 },
    { id: "object:none", kind: "object", label: "No object", count: 1 },
  ],
  links: [
    { source: "hand:right", target: "finger:index", count: 2 },
    { source: "finger:index", target: "movement:tap", count: 2 },
    { source: "movement:tap", target: "object:cup", count: 2 },
    { source: "hand:right", target: "finger:whole_hand", count: 1 },
    { source: "finger:whole_hand", target: "movement:hand_enter", count: 1 },
    { source: "movement:hand_enter", target: "object:none", count: 1 },
  ],
  events: [
    { id: "e1", video_id: "v", path: ["hand:right", "finger:whole_hand", "movement:hand_enter", "object:none"], label: "Hand enters frame",
      start_frame: 0, end_frame: 5, start_s: 0, end_s: 0.17, confidence: 0.9, status: "auto_detected" },
    { id: "e2", video_id: "v", path: ["hand:right", "finger:index", "movement:tap", "object:cup"], label: "Tap",
      start_frame: 30, end_frame: 34, start_s: 1, end_s: 1.13, confidence: 0.7, status: "auto_detected" },
    { id: "e3", video_id: "v", path: ["hand:right", "finger:index", "movement:tap", "object:cup"], label: "Tap",
      start_frame: 60, end_frame: 63, start_s: 2, end_s: 2.1, confidence: 0.5, status: "needs_review" },
  ],
};

describe("interaction graph", () => {
  it("lays nodes out in the Hand → Finger → Movement → Object columns, links sized by events", () => {
    const layout = layoutGraph(graph);
    expect(layout.nodes.map((n) => [n.id, n.column])).toEqual([
      ["hand:right", 0], ["finger:index", 1], ["finger:whole_hand", 1], ["movement:tap", 2], ["movement:hand_enter", 2],
      ["object:cup", 3], ["object:none", 3],
    ]);
    const hand = layout.byId.get("hand:right")!;
    const fingers = layout.nodes.filter((n) => n.column === 1);
    expect(hand.y).toBeCloseTo((fingers[0].y + fingers[1].y) / 2); // a shorter column is centred
    const w = Object.fromEntries(layout.links.map((l) => [`${l.source}>${l.target}`, l.width]));
    expect(w["hand:right>finger:index"]).toBe(10);
    expect(w["hand:right>finger:whole_hand"]).toBeLessThan(10);
  });

  it("follows the chains through a hovered node", () => {
    expect([...pathsThrough(graph, "object:cup").events]).toEqual(["e2", "e3"]);
    expect(pathsThrough(graph, "object:cup").nodes.has("finger:whole_hand")).toBe(false);
    expect(pathsThrough(graph, null).nodes.size).toBe(0);
  });

  it("draws the time range and a table view", () => {
    const { container } = render(<InteractionGraphView graph={graph} duration={3} />);
    expect(container.querySelectorAll("[data-node]")).toHaveLength(7);
    expect(container.querySelectorAll("rect[data-event]")).toHaveLength(3);
    fireEvent.focus(container.querySelector('[data-node="movement:hand_enter"]')!);
    const dim = [...container.querySelectorAll("rect[data-event]")].map((r) => r.getAttribute("fill-opacity"));
    expect(dim).toEqual(["0.85", "0.15", "0.15"]);
    fireEvent.click(screen.getByLabelText("Table view"));
    expect(screen.getAllByRole("row")).toHaveLength(4);
    expect(screen.getByText("1.00–1.13 s")).toBeInTheDocument();
  });
});

describe("evidence", () => {
  it("pairs measurements with the thresholds they were compared to", () => {
    expect(thresholdFor("pinch", "thumb_index_distance", { pinch_distance: 0.3 })).toBe(0.3);
    expect(thresholdFor("pinch", "wrist_x_px", { pinch_distance: 0.3 })).toBeNull();
    expect(measurementUnit("wrist_speed_px_s")).toBe("px/s");
    expect(measurementUnit("roll_turned_deg")).toBe("°");
    expect(frameRuns([3, 4, 5, 9, 11, 12])).toEqual([[3, 5], [9, 9], [11, 12]]);
  });

  it("charts each measurement with its threshold and moves a crosshair from the keyboard", () => {
    vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
    const pick = vi.fn();
    const { container } = render(
      <EvidenceCharts className="pinch" frames={[10, 11, 12]} measurements={{ thumb_index_distance: [0.1, 0.12, 0.2], index_straightness: [0.8, 0.8, 0.81] }}
                      thresholds={{ pinch_distance: 0.3, pinch_index_straightness: 0.6 }} onPick={pick} />,
    );
    expect(container.querySelectorAll("figure")).toHaveLength(2);
    expect(container.querySelectorAll("line[stroke-dasharray]")).toHaveLength(2); // a threshold line per chart
    fireEvent.keyDown(screen.getByTestId("evidence-charts"), { key: "ArrowRight" });
    fireEvent.keyDown(screen.getByTestId("evidence-charts"), { key: "ArrowRight" });
    expect(pick).toHaveBeenLastCalledWith(11);
    expect(container.textContent).toContain("0.12 at f11");
  });
});

describe("ObjectOverlay", () => {
  it("draws the boxes of the frame on screen, labelled, with one object emphasised", async () => {
    const fetch = vi.fn(async () =>
      new Response(JSON.stringify({ run_id: "o1", model_version_id: "m", frame_from: 0, frame_to: 599, frames: [
        { frame: 2, timestamp_s: 0.07, objects: [
          { track_id: 1, label: "cup", score: 0.83, bbox: [0.1, 0.2, 0.3, 0.4] },
          { track_id: 2, label: "book", score: 0.5, bbox: [0.6, 0.1, 0.2, 0.2] },
        ] },
      ] })),
    );
    vi.stubGlobal("fetch", fetch);
    const store = createFrameStore(0);
    const { container } = render(<ObjectOverlay runId="o1" frameStore={store} highlight={1} />);
    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/v1/cv/runs/o1/objects?frame_from=0&frame_to=599", expect.anything()));
    expect(container.querySelector("[data-testid=object-overlay]")).toBeNull();
    act(() => store.set(2));
    await waitFor(() => expect(container.querySelectorAll("[data-track]")).toHaveLength(2));
    const cup = container.querySelector('[data-track="1"]') as HTMLElement;
    expect(cup.style.left).toBe("10%");
    expect(cup.style.width).toBe("30%");
    expect(cup.style.opacity).toBe("1");
    expect((container.querySelector('[data-track="2"]') as HTMLElement).style.opacity).toBe("0.35");
    expect(screen.getByText("cup #1 · 0.83")).toBeInTheDocument();
  });
});
