import { api, type ApiResult } from "@/lib/api/client";
import type { Page } from "@/lib/api/types";

export interface LevelCount {
  /** `null` when unknown (planned level, or the API call failed): shown as an em dash, never as 0. */
  value: number | null;
  caption: string;
}

function total(res: ApiResult<Page<unknown>>): number | null {
  return res.ok ? res.data.total : null;
}

/**
 * How far the data has climbed, one count per level of lib/pipeline.ts (by level name), from the list
 * endpoints' totals (limit=1, so no rows are transferred). Levels that aren't built get no count.
 */
export async function pipelineCounts(token: string): Promise<Record<string, LevelCount>> {
  const one = { limit: 1 };
  const [uploads, videos, ready, tracked, events, autoDetected, needsReview, versions, exports] = await Promise.all([
    api.uploads(token, one),
    api.videos(token, one),
    api.videos(token, { ...one, status: "ready" }),
    api.cvRuns(token, { ...one, kind: "hand_tracking", status: "succeeded" }),
    api.movementEvents(token, one),
    api.movementEvents(token, { ...one, status: "auto_detected" }),
    api.movementEvents(token, { ...one, status: "needs_review" }),
    api.datasetVersions(token, { ...one, status: "ready" }),
    api.datasetExports(token, { ...one, status: "ready" }),
  ]);
  const eventCount = total(events);
  const [auto, flagged] = [total(autoDetected), total(needsReview)];
  // Reviewed = confirmed, rejected, or corrected: everything not still waiting on a person.
  const reviewed = eventCount === null || auto === null || flagged === null ? null : eventCount - auto - flagged;

  return {
    "Raw Video": { value: total(uploads), caption: "uploads" },
    Ingestion: { value: total(videos), caption: "videos ingested" },
    Processing: { value: total(ready), caption: "ready to view" },
    "Hand & Finger Tracking": { value: total(tracked), caption: "tracking runs" },
    "Movement Detection": { value: eventCount, caption: "movement events" },
    "Human Annotation": { value: reviewed, caption: "events reviewed" },
    "Dataset Versioning": { value: total(versions), caption: "dataset versions" },
    Export: { value: total(exports), caption: "exports" },
  };
}
