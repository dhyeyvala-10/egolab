/**
 * The levels every video climbs, from the spec's pipeline: Raw Video → … → Export (→ Evaluation &
 * Monitoring, a later phase). Each level names the pages that do its work; its status and phases are
 * derived from those pages in lib/nav.ts, so marking a page `built` there moves the level forward here
 * too. A level whose pages are all outside the current plan (lib/nav.ts `PLAN_LAST_PHASE`) isn't shown.
 */
import { ALL_PAGES, FULL_NAV, type NavPage } from "./nav";

const FULL_PAGES = FULL_NAV.flatMap((s) => s.pages);

export type LevelStatus = "live" | "in_progress" | "planned";

export interface PipelineLevel {
  name: string;
  blurb: string;
  pages: NavPage[];
  status: LevelStatus;
  /** "Phase 3" or "Phases 2 & 5". */
  phases: string;
}

const LEVELS: { name: string; blurb: string; hrefs: string[] }[] = [
  {
    name: "Raw Video",
    blurb: "First-person footage straight off the headset, uploaded in resumable chunks to object storage.",
    hrefs: ["/data/upload"],
  },
  {
    name: "Ingestion",
    blurb: "Every file is probed for duration, frame rate, codec, and checksum, and flagged if corrupt or duplicate.",
    hrefs: ["/data/videos", "/data/sessions"],
  },
  {
    name: "Processing",
    blurb: "Derivatives are built so every step can seek frame by frame, and pipelines chain the steps, with retries, quality checks, and schedules.",
    hrefs: ["/data/videos", "/pipelines/runs"],
  },
  {
    name: "Hand & Finger Tracking",
    blurb: "A 21-keypoint skeleton per hand, per frame, plus finger velocity, acceleration, visibility, and occlusion.",
    hrefs: ["/cv/hands", "/cv/fingers"],
  },
  {
    name: "Movement Detection",
    blurb: "Reach, grasp, pinch, and lift become confidence-scored events, tied to the objects the hand touches.",
    hrefs: ["/cv/movements", "/cv/objects"],
  },
  {
    name: "Human Annotation",
    blurb: "People confirm, reject, or correct what the models found, in a frame-accurate inspector.",
    hrefs: ["/annotation/inspector", "/annotation/queue", "/annotation/review"],
  },
  {
    name: "Dataset Versioning",
    blurb: "Filtered slices frozen into immutable versions, each with a content hash and full lineage.",
    hrefs: ["/datasets/builder", "/datasets/versions", "/datasets/lineage"],
  },
  {
    name: "Export",
    blurb: "Ship a version as COCO, JSON Lines, Parquet, WebDataset, or the native Ego Labs format.",
    hrefs: ["/datasets/exports"],
  },
  {
    name: "Evaluation & Monitoring",
    blurb: "Per-class precision, recall, and F1 against reviewed ground truth, plus live processing health.",
    hrefs: ["/models/evaluation", "/realtime/processing"],
  },
];

export function levelStatus(pages: NavPage[]): LevelStatus {
  const built = pages.filter((p) => p.built).length;
  if (built === pages.length) return "live";
  return built > 0 ? "in_progress" : "planned";
}

export function phaseLabel(pages: NavPage[]): string {
  const phases = [...new Set(pages.map((p) => p.phase))].sort((a, b) => a - b);
  if (phases.length === 1) return `Phase ${phases[0]}`;
  return `Phases ${phases.slice(0, -1).join(", ")} & ${phases[phases.length - 1]}`;
}

export const PIPELINE: PipelineLevel[] = LEVELS.flatMap(({ name, blurb, hrefs }) => {
  if (!hrefs.every((href) => FULL_PAGES.some((p) => p.href === href))) {
    throw new Error(`Pipeline level "${name}" names a page that is not in lib/nav.ts`);
  }
  const pages = hrefs.flatMap((href) => ALL_PAGES.filter((p) => p.href === href));
  if (!pages.length) return []; // every page of it is in a later phase than the plan
  return [{ name, blurb, pages, status: levelStatus(pages), phases: phaseLabel(pages) }];
});

export const LEVEL_STATUS_LABEL: Record<LevelStatus, string> = {
  live: "Live",
  in_progress: "In progress",
  planned: "Planned",
};
