/** Dataset builder and version helpers (spec Phase 6). */
import type { DatasetSpec as ApiSpec, VersionCounts as ApiCounts } from "@/lib/api/types";

/** The spec with every field present (the API fills defaults; the generated type marks them optional). */
export type Spec = { filters: Required<NonNullable<ApiSpec["filters"]>>; split: Required<NonNullable<ApiSpec["split"]>> };
type SplitCounts = { train: number; val: number; test: number };
export type Counts = {
  splits: SplitCounts; groups: SplitCounts; classes: Record<string, SplitCounts>; statuses: Record<string, number>;
  sources: Record<string, number>; videos: number;
};

export const SPLITS = ["train", "val", "test"] as const;
export type Split = (typeof SPLITS)[number];

export const STATUS_OPTIONS = [
  { value: "confirmed", label: "Confirmed" },
  { value: "auto_detected", label: "Not reviewed" },
  { value: "needs_review", label: "Flagged" },
  { value: "rejected", label: "Rejected" },
] as const;

export const GROUP_OPTIONS = [
  { value: "session", label: "Session", hint: "A capture session never spans two splits" },
  { value: "operator", label: "Operator", hint: "A person's recordings stay in one split" },
  { value: "video", label: "Video", hint: "A video stays in one split" },
  { value: "sample", label: "None", hint: "Each sample is split on its own" },
] as const;

export const FORMAT_INFO: Record<string, { label: string; hint: string }> = {
  coco: { label: "COCO", hint: "Keypoint annotations per split, a key-frame image per sample" },
  jsonl: { label: "JSON Lines", hint: "One sample per line, with per-frame keypoints" },
  parquet: { label: "Parquet", hint: "samples, keypoints, and objects tables" },
  webdataset: { label: "WebDataset", hint: "Tar shards: .json, .jpg, .keypoints.json per sample" },
  egolabs: { label: "Ego Labs", hint: "Native: everything, plus evidence and raw-file provenance" },
};

export function defaultSpec(): Spec {
  return {
    filters: {
      session_ids: [], device_ids: [], environments: [], video_ids: [], exclude_quality_flags: [], classes: [],
      statuses: ["confirmed"], human_verified_only: false, min_confidence: null, max_confidence: null, handedness: [],
      object_labels: [], require_object: null,
    },
    split: { train: 0.8, val: 0.1, test: 0.1, group_by: "session", seed: 0 },
  };
}

export function fullSpec(spec: ApiSpec): Spec {
  const d = defaultSpec();
  return { filters: { ...d.filters, ...spec.filters } as Spec["filters"], split: { ...d.split, ...spec.split } as Spec["split"] };
}

export function fullCounts(c: ApiCounts | null | undefined): Counts {
  const zero = { train: 0, val: 0, test: 0 };
  return {
    splits: { ...zero, ...c?.splits }, groups: { ...zero, ...c?.groups },
    classes: Object.fromEntries(Object.entries(c?.classes ?? {}).map(([k, v]) => [k, { ...zero, ...v }])),
    statuses: c?.statuses ?? {}, sources: c?.sources ?? {}, videos: c?.videos ?? 0,
  };
}

export function totalSamples(c: Counts): number {
  return SPLITS.reduce((n, s) => n + c.splits[s], 0);
}

export function shortHash(h: string | null | undefined): string {
  return h ? `${h.slice(0, 12)}…` : "—";
}

/** The spec's filters in words, for version pages ("Confirmed only · classes grasp, pinch · …"). */
export function describeFilters(api: ApiSpec, names: Record<string, string> = {}): string[] {
  const spec = fullSpec(api);
  const f = spec.filters;
  const out: string[] = [];
  const statuses = f.statuses.map((s) => STATUS_OPTIONS.find((o) => o.value === s)?.label ?? s);
  out.push(`Review: ${statuses.join(", ")}${f.human_verified_only ? " (by a person only)" : ""}`);
  if (f.session_ids.length) out.push(`Sessions: ${f.session_ids.map((i) => names[i] ?? i.slice(0, 8)).join(", ")}`);
  if (f.device_ids.length) out.push(`Devices: ${f.device_ids.map((i) => names[i] ?? i.slice(0, 8)).join(", ")}`);
  if (f.environments.length) out.push(`Environments: ${f.environments.join(", ")}`);
  if (f.exclude_quality_flags.length) out.push(`Without: ${f.exclude_quality_flags.join(", ").replace(/_/g, " ")}`);
  if (f.classes.length) out.push(`Classes: ${f.classes.join(", ").replace(/_/g, " ")}`);
  if (f.min_confidence != null || f.max_confidence != null) out.push(`Confidence ${f.min_confidence ?? 0}–${f.max_confidence ?? 1} (predictions)`);
  if (f.handedness.length) out.push(`Hand: ${f.handedness.join(", ")}`);
  if (f.object_labels.length) out.push(`Objects: ${f.object_labels.join(", ")}`);
  if (f.require_object != null) out.push(f.require_object ? "With an object" : "Without an object");
  const s = spec.split;
  out.push(`Split ${Math.round(s.train * 100)}/${Math.round(s.val * 100)}/${Math.round(s.test * 100)} by ${s.group_by}, seed ${s.seed}`);
  return out;
}
