import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { niceCeil } from "@/components/cv/FingerCharts";
import { SkeletonOverlay } from "@/components/cv/SkeletonOverlay";
import { createFrameStore } from "@/lib/inspector/frameStore";
import { CONNECTIONS, FINGER_JOINTS, percent } from "@/lib/cv/skeleton";

const keypoints = Array.from({ length: 21 }, (_, i) => [0.2 + i * 0.01, 0.5] as [number, number]);

function frames(from: number, to: number) {
  return {
    run_id: "r1",
    model_version_id: "mv1",
    frame_from: from,
    frame_to: to,
    frames: [
      {
        frame: 3,
        timestamp_s: 0.1,
        hands: [{ track_id: 7, handedness: "left", confidence: 0.91, bbox: [0.2, 0.4, 0.2, 0.2], keypoints,
                  fingers: [{ finger: "index", visibility: 1, occluded: true }] }],
      },
    ],
  };
}

afterEach(() => vi.unstubAllGlobals());

describe("SkeletonOverlay", () => {
  it("draws 21 joints and every bone for hands on the current frame only", async () => {
    const fetch = vi.fn(async (url: string) => {
      const u = new URL(url, "http://x");
      return new Response(JSON.stringify(frames(Number(u.searchParams.get("frame_from")), Number(u.searchParams.get("frame_to")))));
    });
    vi.stubGlobal("fetch", fetch);
    const store = createFrameStore(0);
    const { container } = render(<SkeletonOverlay runId="r1" frameStore={store} aspect={4 / 3} />);
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(fetch.mock.calls[0][0]).toBe("/api/v1/cv/runs/r1/frames?frame_from=0&frame_to=599");
    expect(container.querySelector("[data-testid=skeleton-overlay]")).toBeNull(); // no hand on frame 0

    act(() => store.set(3));
    await waitFor(() => expect(container.querySelector("[data-testid=skeleton-overlay]")).not.toBeNull());
    const joints = container.querySelectorAll('line[stroke-width="8"]');
    expect(joints).toHaveLength(21);
    expect(container.querySelectorAll('line[stroke-width="2"]')).toHaveLength(CONNECTIONS.length);
    // The index fingertip is estimated hidden: drawn hollow.
    expect(container.querySelectorAll('line[stroke-width="4"]')).toHaveLength(1);
    expect(Number(joints[8].getAttribute("x1"))).toBeCloseTo(keypoints[8][0] * 1000);
    expect(screen.getByText("L #7 · 0.91")).toBeInTheDocument();

    act(() => store.set(700)); // next window
    await waitFor(() => expect(fetch).toHaveBeenLastCalledWith("/api/v1/cv/runs/r1/frames?frame_from=600&frame_to=1199", expect.anything()));
  });
});

describe("chart scale and schema", () => {
  it("rounds axis maxima to nice numbers", () => {
    expect(niceCeil(0)).toBe(1);
    expect(niceCeil(47)).toBe(50);
    expect(niceCeil(212)).toBe(250);
    expect(niceCeil(1001)).toBe(2000);
    expect(niceCeil(0.8)).toBe(1);
  });

  it("matches the backend hand-21 layout", () => {
    expect(new Set(CONNECTIONS.flat()).size).toBe(21);
    expect(Object.values(FINGER_JOINTS).flat()).toEqual(Array.from({ length: 20 }, (_, i) => i + 1));
    expect(percent(0.256, 1)).toBe("25.6%");
    expect(percent(null)).toBe("—");
  });
});
