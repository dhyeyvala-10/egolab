/**
 * Which stored threshold a rule compared each measurement against, per movement class, so an evidence chart
 * can draw the line the values had to cross. Measurements without an entry are shown without a line.
 */
export const THRESHOLD_FOR: Record<string, Record<string, string>> = {
  pinch: { thumb_index_distance: "pinch_distance", index_straightness: "pinch_index_straightness" },
  point: { index_straightness: "extended_straightness" },
  gesture: { wrist_speed_hand_sizes_s: "still_speed" },
  swipe: { wrist_speed_px_s: "swipe_speed_px_s" },
  reach: {},
  grasp: { curled_fingers: "grasp_curled" },
  manipulate: { fingertip_speed_hand_sizes_s: "manipulate_speed" },
};

const UNITS: [RegExp, string][] = [
  [/_px_s$/, "px/s"],
  [/_px$/, "px"],
  [/_deg_s$/, "°/s"],
  [/_deg$/, "°"],
  [/_hand_sizes_s$/, "hand sizes/s"],
  [/distance$/, "hand sizes"],
];

export function measurementUnit(name: string): string {
  return UNITS.find(([re]) => re.test(name))?.[1] ?? "";
}

export function measurementLabel(name: string): string {
  const base = name.replace(/_(px_s|px|deg_s|deg|hand_sizes_s)$/, "").replace(/_/g, " ");
  return base.charAt(0).toUpperCase() + base.slice(1);
}

export function thresholdFor(className: string, measurement: string, thresholds: Record<string, number>): number | null {
  const key = THRESHOLD_FOR[className]?.[measurement];
  return key != null && typeof thresholds[key] === "number" ? thresholds[key] : null;
}

/** Evidence frames as runs of consecutive frames, for the timeline: [[start, end], …]. */
export function frameRuns(frames: number[]): [number, number][] {
  const out: [number, number][] = [];
  for (const f of frames) {
    const last = out.at(-1);
    if (last && f === last[1] + 1) last[1] = f;
    else out.push([f, f]);
  }
  return out;
}
