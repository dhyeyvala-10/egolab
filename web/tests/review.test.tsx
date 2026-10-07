import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CorrectForm } from "@/components/review/CorrectForm";
import { DailyChart } from "@/components/review/DailyChart";
import { ReviewCards } from "@/components/review/ReviewCards";
import type { MovementClassRead, MovementEventSummary, ReviewGroup } from "@/lib/api/types";
import { bulkFilters, queueQuery, reviewKey, scopeLabel } from "@/lib/review";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }) }));

const group = (over: Partial<ReviewGroup>): ReviewGroup => ({
  key: "grasp", label: "Grasp", movement_class: { id: "c1", name: "grasp", label: "Grasp" }, total: 10, pending: 6,
  needs_review: 2, confirmed: 2, auto_accepted: 1, rejected: 1, corrected: 1, mean_confidence: 0.7, min_confidence: 0.41, ...over,
});

const event = {
  id: "e1", movement_class: { id: "c1", name: "grasp", label: "Grasp" }, start_frame: 10, end_frame: 40, handedness: "right",
  fingers: ["thumb", "index"], object_label: "cup", object_track_id: 2, confidence: 0.8,
} as unknown as MovementEventSummary;

const classes = [
  { id: "c1", name: "grasp", label: "Grasp", active: true },
  { id: "c2", name: "pinch", label: "Pinch", active: true },
  { id: "c3", name: "tap", label: "Tap", active: false },
] as unknown as MovementClassRead[];

describe("ReviewCards", () => {
  it("shows what is left per class and links into that class's workspace", () => {
    render(<ReviewCards groups={[group({}), group({ key: "tap", label: "Tap", movement_class: { id: "c3", name: "tap", label: "Tap" }, pending: 0, needs_review: 0, total: 3, confirmed: 3, rejected: 0, corrected: 0 })]}
                        hrefFor={(g) => `/annotation/review/work?class=${g.key}`} />);
    const grasp = screen.getByRole("link", { name: /Grasp/ });
    expect(grasp).toHaveAttribute("href", "/annotation/review/work?class=grasp");
    expect(grasp).toHaveTextContent("6to review");
    expect(grasp).toHaveTextContent("2 flagged");
    expect(grasp).toHaveTextContent("4 of 10 reviewed · 1 auto");
    expect(screen.getByRole("img", { name: /Accepted 2, Corrected 1, Rejected 1, Needs review 2, Not reviewed 4/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Tap/ })).toHaveTextContent("3 of 3 reviewed");
  });
});

describe("review keys and scope", () => {
  const key = (k: string, target: EventTarget | null = document.body) => reviewKey({ key: k, ctrlKey: false, metaKey: false, altKey: false, target });
  it("maps A/R/C/F/N/P/L and leaves typing alone", () => {
    expect(["a", "R", "c", "f", "n", "s", "p", "l", "x"].map((k) => key(k))).toEqual(["accept", "reject", "correct", "flag", "next", "next", "prev", "loop", null]);
    const input = document.createElement("input");
    expect(key("a", input)).toBeNull();
    expect(reviewKey({ key: "a", ctrlKey: true, metaKey: false, altKey: false, target: null })).toBeNull();
  });
  it("turns a workspace URL into the queue query and the same bulk filters", () => {
    const q = { class: "grasp", object: "cup", session_id: "s1" };
    expect(queueQuery(q)).toMatchObject({ class: "grasp", object_label: "cup", session_id: "s1", sort: "priority" });
    expect(bulkFilters(q)).toMatchObject({ classes: ["grasp"], object_label: "cup", session_id: "s1", statuses: ["auto_detected", "needs_review"] });
    expect(bulkFilters({ no_object: "1", status: "needs_review" })).toMatchObject({ no_object: true, statuses: ["needs_review"] });
    expect(scopeLabel(q, "Grasp")).toBe("Grasp · with cup");
    expect(scopeLabel({})).toBe("All classes");
  });
});

describe("CorrectForm", () => {
  it("sends only what changed", async () => {
    const onSubmit = vi.fn().mockResolvedValue(null);
    render(<CorrectForm event={event} classes={classes} onSubmit={onSubmit} />);
    expect(screen.queryByRole("option", { name: "Tap" })).toBeNull(); // inactive classes aren't offered
    fireEvent.change(screen.getByLabelText("Movement"), { target: { value: "pinch" } });
    fireEvent.change(screen.getByLabelText("End frame"), { target: { value: "35" } });
    fireEvent.click(screen.getByLabelText("No object"));
    fireEvent.click(screen.getByRole("button", { name: "Save correction" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith({ class: "pinch", end_frame: 35, clear_object: true }));
  });
  it("says so when nothing changed, and checks the frames", async () => {
    const onSubmit = vi.fn();
    render(<CorrectForm event={event} classes={classes} onSubmit={onSubmit} />);
    fireEvent.click(screen.getByRole("button", { name: "Save correction" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Nothing changed");
    fireEvent.change(screen.getByLabelText("Start frame"), { target: { value: "50" } });
    fireEvent.click(screen.getByRole("button", { name: "Save correction" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("end at or after start");
    expect(onSubmit).not.toHaveBeenCalled();
  });
});

describe("DailyChart", () => {
  it("stacks human under auto per day, with a readout and a table", () => {
    render(<DailyChart days={[{ day: "2026-09-23", human: 4, auto_rule: 2 }, { day: "2026-09-24", human: 1, auto_rule: 0 }]} />);
    expect(screen.getByText("Human reviews")).toBeInTheDocument();
    expect(document.querySelectorAll("rect.fill-human")).toHaveLength(2);
    expect(document.querySelectorAll("rect.fill-ai")).toHaveLength(1);
    fireEvent.mouseEnter(document.querySelectorAll("svg g")[0]);
    expect(screen.getByText("2026-09-23: 4 human, 2 auto")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Table" }));
    expect(screen.getByRole("table")).toHaveTextContent("2026-09-24");
  });
});
