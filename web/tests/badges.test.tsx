import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  ConfidenceBadge,
  confidenceLevel,
  EmptyState,
  SourceBadge,
  StatCard,
  StatusBadge,
  statusTone,
} from "@/components/ui";

describe("confidenceLevel", () => {
  it("buckets by threshold", () => {
    expect(confidenceLevel(0.95)).toBe("high");
    expect(confidenceLevel(0.85)).toBe("high");
    expect(confidenceLevel(0.84)).toBe("medium");
    expect(confidenceLevel(0.6)).toBe("medium");
    expect(confidenceLevel(0.59)).toBe("low");
  });
});

describe("ConfidenceBadge", () => {
  it("renders two decimals, clamps, and carries the model version", () => {
    render(<ConfidenceBadge value={1.4} modelVersion="mediapipe-hands@0.10" />);
    const badge = screen.getByText("1.00");
    expect(badge).toHaveAttribute("data-level", "high");
    expect(badge.getAttribute("title")).toContain("mediapipe-hands@0.10");
  });

  it("marks low confidence", () => {
    render(<ConfidenceBadge value={0.31} />);
    expect(screen.getByText("0.31")).toHaveAttribute("data-level", "low");
  });
});

describe("StatusBadge", () => {
  it("maps job and review statuses to tones", () => {
    expect(statusTone("failed")).toBe("error");
    expect(statusTone("needs_review")).toBe("warning");
    expect(statusTone("running")).toBe("running");
    expect(statusTone("something_new")).toBe("neutral");
  });

  it("humanizes the label", () => {
    render(<StatusBadge status="auto_detected" />);
    // An unreviewed prediction is neutral, not a pulsing "running" state.
    expect(screen.getByText("Auto detected").closest("[data-tone]")).toHaveAttribute("data-tone", "neutral");
  });
});

describe("SourceBadge", () => {
  it("distinguishes AI from human annotations", () => {
    render(
      <>
        <SourceBadge source="auto" />
        <SourceBadge source="human" />
        <SourceBadge source="auto_corrected" />
      </>,
    );
    expect(screen.getByText("AI")).toHaveAttribute("data-source", "auto");
    expect(screen.getByText("Human")).toHaveAttribute("data-source", "human");
    expect(screen.getByText("AI · corrected")).toHaveAttribute("data-source", "auto_corrected");
  });
});

describe("StatCard", () => {
  it("shows an em dash instead of a number when there is no data", () => {
    render(<StatCard label="Videos" value={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  it("formats numbers and links through to the records", () => {
    render(<StatCard label="Videos" value={12345} href="/data/videos" />);
    expect(screen.getByText("12,345")).toBeInTheDocument();
    expect(screen.getByRole("link")).toHaveAttribute("href", "/data/videos");
  });
});

describe("EmptyState", () => {
  it("renders title, description, and action", () => {
    render(<EmptyState title="No sessions yet" description="Upload a video to start." action={<button>Upload</button>} />);
    expect(screen.getByRole("status")).toHaveTextContent("No sessions yet");
    expect(screen.getByText("Upload a video to start.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Upload" })).toBeInTheDocument();
  });
});
