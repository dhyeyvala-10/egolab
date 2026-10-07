import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Timeline, type TimelineTrack } from "@/components/ui";
import { clockFromIndex, nominalClock } from "@/lib/inspector/frames";
import { createFrameStore } from "@/lib/inspector/frameStore";
import { actionFor } from "@/lib/inspector/shortcuts";
import { followView, MIN_SPAN, panView, zoomView } from "@/lib/inspector/view";
import { normaliseBox } from "@/lib/inspector/types";

describe("frame clock", () => {
  // The index the backend builds for a variable frame rate proxy: 41 frames at 30 fps, then 15 fps.
  const vfr = { version: 1, frame_count: 50, time_base: [1, 15360] as [number, number], runs: [[0, 512, 41] as [number, number, number], [21504, 1024, 9] as [number, number, number]] };

  it("expands run-length encoded timestamps", () => {
    const clock = clockFromIndex(vfr);
    expect(clock.exact).toBe(true);
    expect(clock.frameCount).toBe(50);
    expect(clock.times[1]).toBeCloseTo(1 / 30);
    expect(clock.times[41]).toBeCloseTo(21504 / 15360);
    expect(clock.times[49]).toBeCloseTo((21504 + 8 * 1024) / 15360);
  });

  it("seeks into each frame's display interval, so frame N is the one shown", () => {
    for (const clock of [clockFromIndex(vfr), nominalClock(300, 29.97)]) {
      for (let n = 0; n < clock.frameCount; n++) {
        const t = clock.seekTime(n);
        expect(t).toBeGreaterThan(clock.times[n]);
        if (n + 1 < clock.frameCount) expect(t).toBeLessThan(clock.times[n + 1]);
        expect(clock.frameAt(t)).toBe(n);
      }
    }
  });

  it("maps a presented frame's timestamp back to its index exactly", () => {
    const clock = clockFromIndex(vfr);
    for (let n = 0; n < 50; n++) expect(clock.frameAt(clock.times[n])).toBe(n);
    expect(clock.frameAt(-1)).toBe(0);
    expect(clock.frameAt(1e9)).toBe(49);
    expect(clock.clamp(-5)).toBe(0);
    expect(clock.clamp(80)).toBe(49);
  });

  it("keeps frames a single clock tick apart distinct", () => {
    // From a real proxy: frame 123 lands 1/15360 s after frame 122 (source timestamp jitter).
    const jitter = { version: 1, frame_count: 126, time_base: [1, 15360] as [number, number], runs: [[0, 512, 123], [62465, 1023, 2], [64000, 512, 1]] as [number, number, number][] };
    const clock = clockFromIndex(jitter);
    expect(clock.frameAt(clock.times[122])).toBe(122);
    expect(clock.frameAt(clock.times[123])).toBe(123);
    expect(clock.frameAt(clock.seekTime(122))).toBe(122);
    expect(clock.frameAt(Math.round(clock.times[122] * 1e6) / 1e6)).toBe(122); // media time rounded to µs
  });

  it("falls back to nominal FPS without an index", () => {
    const clock = nominalClock(54_000, 30);
    expect(clock.exact).toBe(false);
    expect(clock.frameAt(60)).toBe(1800);
  });
});

describe("frame store", () => {
  it("notifies only on change", () => {
    const store = createFrameStore();
    const fn = vi.fn();
    store.subscribe(fn);
    store.set(3);
    store.set(3);
    store.set(4);
    expect(fn).toHaveBeenCalledTimes(2);
    expect(store.get()).toBe(4);
  });
});

describe("timeline view", () => {
  const frames = 54_000; // 30 minutes at 30 fps

  it("zooms around the anchor and never past the video", () => {
    const whole = { start: 0, end: frames - 1 };
    const zoomed = zoomView(whole, 0.1, 27_000, frames);
    expect(zoomed.end - zoomed.start + 1).toBe(5_400);
    expect(zoomed.start).toBeLessThanOrEqual(27_000);
    expect(zoomed.end).toBeGreaterThanOrEqual(27_000);
    expect(zoomView(zoomed, 1e-6, 27_000, frames).end - zoomView(zoomed, 1e-6, 27_000, frames).start + 1).toBe(MIN_SPAN);
    expect(zoomView(zoomed, 1e6, 0, frames)).toEqual(whole);
  });

  it("pans within bounds and follows the playhead", () => {
    const v = { start: 1000, end: 1999 };
    expect(panView(v, -5000, frames)).toEqual({ start: 0, end: 999 });
    expect(panView(v, 1e9, frames)).toEqual({ start: 53_000, end: 53_999 });
    expect(followView(v, 1500, frames)).toBeNull();
    expect(followView(v, 2000, frames)).toEqual({ start: 1950, end: 2949 });
  });
});

describe("shortcuts", () => {
  const key = (k: string, extra: Partial<{ shiftKey: boolean; ctrlKey: boolean; target: EventTarget }> = {}) =>
    actionFor({ key: k, shiftKey: false, ctrlKey: false, metaKey: false, altKey: false, target: document.body, ...extra });

  it("maps the spec's keys", () => {
    expect(key(" ")).toBe("togglePlay");
    expect(key("ArrowLeft")).toBe("prevFrame");
    expect(key("ArrowRight")).toBe("nextFrame");
    expect(key("ArrowLeft", { shiftKey: true })).toBe("prevEvent");
    expect(key("ArrowRight", { shiftKey: true })).toBe("nextEvent");
    expect(key("a")).toBe("create");
    expect(key("r")).toBe("review");
    expect(key("Delete")).toBe("delete");
    expect(key("Escape")).toBe("cancel");
  });

  it("leaves typing and browser shortcuts alone", () => {
    const input = document.createElement("input");
    expect(key("a", { target: input })).toBeNull();
    expect(key("Delete", { target: document.createElement("textarea") })).toBeNull();
    expect(key("r", { ctrlKey: true })).toBeNull();
    expect(key("Escape", { target: input })).toBe("cancel");
    const box = document.createElement("input");
    box.type = "checkbox";
    expect(key(" ", { target: box })).toBe("togglePlay");
  });
});

describe("box drawing", () => {
  it("normalises any drag direction and clamps to the frame", () => {
    expect(normaliseBox({ x: 0.6, y: 0.8 }, { x: 0.2, y: 0.4 })).toEqual([0.2, 0.4, 0.4, 0.4]);
    expect(normaliseBox({ x: -0.5, y: 0.5 }, { x: 1.5, y: 2 })).toEqual([0, 0.5, 1, 0.5]);
  });
});

describe("timeline on a 30-minute video", () => {
  const frames = 54_000;

  it("draws a busy track as density buckets, not 27,000 segments", () => {
    const buckets = Array.from({ length: 300 }, (_, i) => ({ start: i * 180, end: i * 180 + 179, count: 90 }));
    const tracks: TimelineTrack[] = [
      { id: "hand", label: "Hand detections", kind: "ai", segments: [], buckets, total: 27_000 },
      { id: "pipeline", label: "Pipeline events", kind: "event", segments: [], total: 0, emptyHint: "Filled from Phase 7" },
    ];
    const onBucket = vi.fn();
    const { container } = render(<Timeline tracks={tracks} frameCount={frames} fps={30} onBucketClick={onBucket} />);
    expect(container.querySelectorAll("[data-bucket]")).toHaveLength(300);
    expect(container.querySelectorAll("[data-segment]")).toHaveLength(0);
    expect(screen.getByText("27000")).toBeInTheDocument();
    expect(screen.getByText("Filled from Phase 7")).toBeInTheDocument();
    fireEvent.click(container.querySelector('[data-bucket="180"]')!);
    expect(onBucket).toHaveBeenCalledWith(buckets[1], tracks[0]);
  });

  it("moves the playhead without re-rendering the tracks", () => {
    const segments = Array.from({ length: 400 }, (_, i) => ({ id: `s${i}`, start: i * 100, end: i * 100 + 50, label: "reach" }));
    const tracks: TimelineTrack[] = [{ id: "human", label: "Human annotations", kind: "human", segments }];
    const view = { start: 0, end: 5999 };
    const { container, rerender } = render(<Timeline tracks={tracks} frameCount={frames} fps={30} view={view} currentFrame={0} />);
    const first = container.querySelector('[data-segment="s10"]');
    expect(container.querySelectorAll("[data-segment]")).toHaveLength(60); // only what's in view
    act(() => rerender(<Timeline tracks={tracks} frameCount={frames} fps={30} view={view} currentFrame={1234} />));
    expect(container.querySelector('[data-segment="s10"]')).toBe(first); // same DOM node: row not rebuilt
    expect(screen.getByTestId("timeline-playhead").style.left).toContain(String(1234 / 6000));
  });

  it("highlights the selected segment and reports clicks on it", () => {
    const onClick = vi.fn();
    const onSeek = vi.fn();
    const tracks: TimelineTrack[] = [{ id: "human", label: "Human annotations", kind: "human", segments: [{ id: "a", start: 0, end: 100, flagged: true }] }];
    const { container } = render(<Timeline tracks={tracks} frameCount={300} fps={30} selectedId="a" onSegmentClick={onClick} onSeek={onSeek} />);
    const seg = container.querySelector('[data-segment="a"]')!;
    expect(seg.getAttribute("data-selected")).toBe("true");
    expect(screen.getByLabelText("Needs review")).toBeInTheDocument();
    fireEvent.click(seg);
    expect(onClick).toHaveBeenCalled();
    expect(onSeek).not.toHaveBeenCalled();
  });
});
