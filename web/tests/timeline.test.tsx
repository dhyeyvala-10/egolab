import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { formatTimecode, Timeline, visibleSegments, type TimelineSegment } from "@/components/ui";

describe("formatTimecode", () => {
  it("formats frames as MM:SS:FF", () => {
    expect(formatTimecode(0, 30)).toBe("00:00:00");
    expect(formatTimecode(29, 30)).toBe("00:00:29");
    expect(formatTimecode(30 * 61 + 5, 30)).toBe("01:01:05");
    expect(formatTimecode(30 * 3600, 30)).toBe("1:00:00:00");
  });
});

describe("visibleSegments", () => {
  // 30-minute video at 30 fps with a 10-frame event every 20 frames.
  const segments: TimelineSegment[] = Array.from({ length: 2700 }, (_, i) => ({ id: `e${i}`, start: i * 20, end: i * 20 + 9 }));

  it("returns only segments intersecting the window", () => {
    const vis = visibleSegments(segments, 1000, 1100);
    expect(vis.map((s) => s.id)).toEqual(["e50", "e51", "e52", "e53", "e54", "e55"]);
  });

  it("includes long segments that start before the window", () => {
    const withLong = [{ id: "long", start: 0, end: 5000 }, ...segments.slice(1)];
    const vis = visibleSegments(withLong, 4000, 4010);
    expect(vis.map((s) => s.id)).toContain("long");
    expect(vis.map((s) => s.id)).toContain("e200");
  });
});

describe("Timeline", () => {
  const tracks = [
    { id: "human", label: "Human annotations", kind: "human" as const, segments: [{ id: "h1", start: 10, end: 20, label: "grasp" }] },
    {
      id: "ai",
      label: "AI annotations",
      kind: "ai" as const,
      segments: [
        { id: "a1", start: 5, end: 8, confidence: 0.91 },
        { id: "a2", start: 200, end: 260 },
      ],
    },
    { id: "hands", label: "Hand detections", kind: "event" as const, segments: [] },
  ];

  it("renders empty tracks and only the segments in view", () => {
    const { container } = render(<Timeline tracks={tracks} frameCount={300} fps={30} view={{ start: 0, end: 100 }} />);
    expect(screen.getByText("Hand detections")).toBeInTheDocument();
    const ids = [...container.querySelectorAll("[data-segment]")].map((el) => el.getAttribute("data-segment"));
    expect(ids).toEqual(["h1", "a1"]);
  });

  it("seeks to the clicked frame", () => {
    const onSeek = vi.fn();
    render(<Timeline tracks={tracks} frameCount={300} fps={30} onSeek={onSeek} currentFrame={0} />);
    const lane = screen.getByTestId("track-ai");
    lane.getBoundingClientRect = () => ({ left: 100, width: 600, top: 0, height: 32, right: 700, bottom: 32, x: 100, y: 0, toJSON: () => ({}) });
    fireEvent.click(lane, { clientX: 400 }); // halfway → frame 150 of 0..299
    expect(onSeek).toHaveBeenCalledWith(150);
    fireEvent.click(lane, { clientX: 5000 });
    expect(onSeek).toHaveBeenLastCalledWith(299);
    expect(screen.getByTestId("timeline-playhead")).toBeInTheDocument();
  });
});
