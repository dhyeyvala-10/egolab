/**
 * Review workspace helpers (spec Phase 5): which events a workspace covers (from the URL), and its keys.
 */
import type { MovementEventStatus, ReviewFilters, Role } from "@/lib/api/types";
import { isTyping } from "@/lib/inspector/shortcuts";

/** URL params a review workspace reads. */
export const WORKSPACE_KEYS = ["class", "object", "no_object", "session_id", "video_id", "status", "sort", "handedness"] as const;
export type WorkspaceQuery = Partial<Record<(typeof WORKSPACE_KEYS)[number], string>>;

export const SORTS = [
  { value: "priority", label: "Priority (combined)" },
  { value: "confidence", label: "Lowest confidence" },
  { value: "disagreement", label: "Most model disagreement" },
  { value: "rarity", label: "Rarest class" },
  { value: "start", label: "Video order" },
] as const;

/** Leads (admin, reviewer) bulk-review and set auto-accept rules; annotators review one event at a time. */
export function isLead(role: Role): boolean {
  return role === "admin" || role === "reviewer";
}

export function canReview(role: Role): boolean {
  return role !== "viewer";
}

/** The workspace URL query → the queue endpoint's query. */
export function queueQuery(q: WorkspaceQuery): Record<string, string | boolean | undefined> {
  return {
    class: q.class,
    object_label: q.object,
    no_object: q.no_object === "1" ? true : undefined,
    session_id: q.session_id,
    video_id: q.video_id,
    handedness: q.handedness,
    status: q.status,
    sort: q.sort ?? "priority",
  };
}

/** The workspace URL query → the filters a bulk review applies (the same events the queue shows). */
export function bulkFilters(q: WorkspaceQuery): ReviewFilters {
  return {
    classes: q.class ? [q.class] : [],
    object_label: q.object ?? null,
    no_object: q.no_object === "1",
    session_id: q.session_id ?? null,
    video_id: q.video_id ?? null,
    handedness: (q.handedness as ReviewFilters["handedness"]) ?? null,
    statuses: q.status ? [q.status as MovementEventStatus] : ["auto_detected", "needs_review"],
    event_ids: [],
    min_confidence: null,
    max_confidence: null,
  };
}

/** What the workspace is about, in words. */
export function scopeLabel(q: WorkspaceQuery, classLabel?: string): string {
  const parts: string[] = [];
  if (q.class) parts.push(classLabel ?? q.class);
  if (q.no_object === "1") parts.push("no object");
  else if (q.object) parts.push(`with ${q.object}`);
  if (!parts.length) return "All classes";
  return parts.join(" · ");
}

export type ReviewKey = "accept" | "reject" | "correct" | "flag" | "next" | "prev" | "loop";

/** Workspace keys: A accept, R reject, C correct, F flag, N/S next, P previous, L loop. */
export function reviewKey(e: { key: string; ctrlKey: boolean; metaKey: boolean; altKey: boolean; target: EventTarget | null }): ReviewKey | null {
  if (e.ctrlKey || e.metaKey || e.altKey || isTyping(e.target)) return null;
  switch (e.key.toLowerCase()) {
    case "a":
      return "accept";
    case "r":
      return "reject";
    case "c":
      return "correct";
    case "f":
      return "flag";
    case "n":
    case "s":
      return "next";
    case "p":
      return "prev";
    case "l":
      return "loop";
    default:
      return null;
  }
}

export const REVIEW_KEYS: { key: string; label: string }[] = [
  { key: "A", label: "Accept" },
  { key: "R", label: "Reject" },
  { key: "C", label: "Correct" },
  { key: "F", label: "Flag for a second look" },
  { key: "N", label: "Skip to next" },
  { key: "P", label: "Previous" },
  { key: "L", label: "Loop the clip on/off" },
  { key: "Space", label: "Play / pause" },
];

export function pct(n: number | null | undefined): string {
  return n == null ? "—" : `${Math.round(n * 1000) / 10}%`;
}
