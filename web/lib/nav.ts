/**
 * Navigation for the Ego Labs app shell.
 *
 * Every page the spec (docs/ego-labs-phased-spec.md) calls for is listed here with the phase that
 * builds it. Pages that are not built yet render the "Not yet built" state from the catch-all route,
 * so adding a real page is: create the route folder, then set `built: true` on its entry.
 *
 * The current plan builds Phases 0–7. Pages of later (optional) phases stay listed in FULL_NAV but are
 * left out of the app until `PLAN_LAST_PHASE` is raised.
 */

export type PhaseId = 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11;

export const PHASES: Record<PhaseId, string> = {
  0: "Foundation",
  1: "Ingestion & Sessions",
  2: "Video Inspector & Manual Annotation",
  3: "CV Worker & Hand/Finger Tracking",
  4: "Movement Classification & Object Interaction",
  5: "Review & Active Learning",
  6: "Datasets, Versioning & Lineage",
  7: "Pipelines",
  8: "Models & Evaluation",
  9: "Real-Time & Overview Command Center",
  10: "Mobile App (React Native / Expo)",
  11: "Differentiators",
};

export type SectionIcon =
  | "overview"
  | "data"
  | "annotation"
  | "cv"
  | "pipelines"
  | "datasets"
  | "models"
  | "realtime"
  | "experiments"
  | "infrastructure"
  | "settings";

export interface NavPage {
  label: string;
  href: string;
  phase: PhaseId;
  /** What the page will do, from the spec. Shown on the "Not yet built" state. */
  summary: string;
  built?: boolean;
}

export interface NavSection {
  id: SectionIcon;
  label: string;
  /** Label in the top bar, where space is tight. Defaults to `label`. */
  short?: string;
  pages: NavPage[];
}

/** The last phase in the current plan: unbuilt pages of later phases aren't shown. */
export const PLAN_LAST_PHASE: PhaseId = 7;

export const FULL_NAV: NavSection[] = [
  {
    id: "overview",
    label: "Overview",
    pages: [
      {
        label: "Overview",
        href: "/dashboard",
        phase: 9,
        summary: "Dataset stats, processing metrics, data quality metrics, and the live activity stream.",
        built: true,
      },
    ],
  },
  {
    id: "data",
    label: "Data",
    pages: [
      { label: "Upload", href: "/data/upload", phase: 1, summary: "Drag-and-drop, resumable multipart uploads direct to object storage.", built: true },
      { label: "Video Library", href: "/data/videos", phase: 1, summary: "Filterable table of every ingested video with ffprobe metadata, checksum, and quality flags.", built: true },
      { label: "Sessions", href: "/data/sessions", phase: 1, summary: "Capture sessions (SESSION_YYYY_MM_DD_NNN) with operator, device, environment, task, and status.", built: true },
      { label: "Devices", href: "/data/devices", phase: 1, summary: "Capture devices and the sessions recorded on each.", built: true },
    ],
  },
  {
    id: "annotation",
    label: "Annotation",
    pages: [
      { label: "Video Inspector", href: "/annotation/inspector", phase: 2, summary: "Frame-accurate player, annotation panel, and multi-track timeline.", built: true },
      { label: "Annotation Queue", href: "/annotation/queue", phase: 2, summary: "Assign sessions and videos to annotators.", built: true },
      { label: "Review", href: "/annotation/review", phase: 5, summary: "Accept, reject, or correct auto annotations, ordered by an active-learning queue.", built: true },
      { label: "Auto Annotation", href: "/annotation/auto", phase: 5, summary: "Run auto-annotation on selected sessions with a chosen model version.", built: true },
    ],
  },
  {
    id: "cv",
    label: "Computer Vision",
    short: "Vision",
    pages: [
      { label: "Hand Tracking", href: "/cv/hands", phase: 3, summary: "Skeleton overlays, per-hand detections, missing-detection and tracking-failure stats.", built: true },
      { label: "Finger Tracking", href: "/cv/fingers", phase: 3, summary: "Per-finger kinematics: velocity, acceleration, visibility, and occlusion.", built: true },
      { label: "Movement Classification", href: "/cv/movements", phase: 4, summary: "Confidence-scored movement events (reach, grasp, pinch, …) linked to their keypoint frames.", built: true },
      { label: "Object Tracking", href: "/cv/objects", phase: 4, summary: "Object detections and hand–object contact.", built: true },
    ],
  },
  {
    id: "pipelines",
    label: "Pipelines",
    pages: [
      { label: "Pipeline Builder", href: "/pipelines/builder", phase: 7, summary: "Visual DAG of processing steps.", built: true },
      { label: "Runs", href: "/pipelines/runs", phase: 7, summary: "Status per step, duration, logs, retries, and failure reasons.", built: true },
      { label: "Schedules", href: "/pipelines/schedules", phase: 7, summary: "Cron-style pipeline schedules.", built: true },
      { label: "Templates", href: "/pipelines/templates", phase: 7, summary: "Reusable pipeline templates.", built: true },
    ],
  },
  {
    id: "datasets",
    label: "Datasets",
    pages: [
      { label: "Dataset Builder", href: "/datasets/builder", phase: 6, summary: "Filter by session, class, confidence, review status, quality flags, device, and environment.", built: true },
      { label: "Versions", href: "/datasets/versions", phase: 6, summary: "Immutable dataset versions with filters, annotation IDs, model versions, and content hash.", built: true },
      { label: "Exports", href: "/datasets/exports", phase: 6, summary: "COCO, JSON Lines, Parquet, WebDataset, and the native Ego Labs format.", built: true },
      { label: "Lineage", href: "/datasets/lineage", phase: 6, summary: "Trace any exported sample back to its annotations, model versions, jobs, and raw frame.", built: true },
    ],
  },
  {
    id: "models",
    label: "Models",
    pages: [
      { label: "Model Registry", href: "/models/registry", phase: 8, summary: "Every adapter version with config, metrics, and the datasets it was evaluated on." },
      { label: "Inference", href: "/models/inference", phase: 8, summary: "Run any registered model on selected videos." },
      { label: "Evaluation", href: "/models/evaluation", phase: 8, summary: "Precision, recall, F1 per class, and keypoint error against human-reviewed ground truth." },
    ],
  },
  {
    id: "realtime",
    label: "Real-Time",
    short: "Live",
    pages: [
      { label: "Event Stream", href: "/realtime/events", phase: 9, summary: "Live feed of system events." },
      { label: "Live Processing", href: "/realtime/processing", phase: 9, summary: "Active jobs, queue depth, processing FPS, and inference latency." },
    ],
  },
  {
    id: "experiments",
    label: "Experiments",
    pages: [
      { label: "Experiments", href: "/experiments", phase: 8, summary: "Configurations and results side by side." },
    ],
  },
  {
    id: "infrastructure",
    label: "Infrastructure",
    short: "Infra",
    pages: [
      { label: "Workers", href: "/infrastructure/workers", phase: 9, summary: "Worker health and GPU/CPU utilisation from real worker telemetry." },
      { label: "System Logs", href: "/infrastructure/logs", phase: 9, summary: "Searchable, filterable structured logs from every job." },
    ],
  },
  {
    id: "settings",
    label: "Settings",
    pages: [
      { label: "Users", href: "/settings/users", phase: 0, summary: "Who has signed in, their access (annotator, reviewer, viewer, or none), and blocking accounts.", built: true },
      { label: "Requests", href: "/settings/requests", phase: 0, summary: "Uploads over the size limit and videos over the length limit, waiting for the admin.", built: true },
      { label: "Limits", href: "/settings/limits", phase: 0, summary: "Upload size and video length limits, and who may start processing.", built: true },
      { label: "Activity", href: "/settings/activity", phase: 0, summary: "Every sign-in and everything everyone did.", built: true },
    ],
  },
];

/** What the app shows: built pages, and unbuilt ones planned up to PLAN_LAST_PHASE. */
export const NAV: NavSection[] = FULL_NAV.map((s) => ({ ...s, pages: s.pages.filter((p) => p.built || p.phase <= PLAN_LAST_PHASE) }))
  .filter((s) => s.pages.length > 0);

export const ALL_PAGES: NavPage[] = NAV.flatMap((s) => s.pages);

export function findPage(pathname: string): NavPage | undefined {
  const clean = pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname;
  return ALL_PAGES.find((p) => p.href === clean);
}

/** True when `pathname` is `href` or one of its sub-routes. */
export function isActive(href: string, pathname: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}
