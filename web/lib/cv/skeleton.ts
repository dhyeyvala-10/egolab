/** The hand-21 layout (mirrors egolabs.cv.keypoints). */
export const FINGERS = ["thumb", "index", "middle", "ring", "pinky"] as const;
export type FingerName = (typeof FINGERS)[number];

export const FINGER_JOINTS: Record<FingerName, [number, number, number, number]> = {
  thumb: [1, 2, 3, 4],
  index: [5, 6, 7, 8],
  middle: [9, 10, 11, 12],
  ring: [13, 14, 15, 16],
  pinky: [17, 18, 19, 20],
};

export const CONNECTIONS: [number, number][] = [
  [0, 1], [1, 2], [2, 3], [3, 4],
  [0, 5], [5, 6], [6, 7], [7, 8],
  [5, 9], [9, 10], [10, 11], [11, 12],
  [9, 13], [13, 14], [14, 15], [15, 16],
  [13, 17], [0, 17], [17, 18], [18, 19], [19, 20],
];

export const TIPS: Record<number, FingerName> = { 4: "thumb", 8: "index", 12: "middle", 16: "ring", 20: "pinky" };

export function percent(n: number | null | undefined, digits = 0): string {
  return n == null ? "—" : `${(n * 100).toFixed(digits)}%`;
}
