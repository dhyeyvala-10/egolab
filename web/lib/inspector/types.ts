import type { AnnotationType } from "@/lib/api/types";

/** [x, y, width, height], normalised to the frame (0–1, origin top left). */
export type Box = [number, number, number, number];

export interface Point {
  name: string;
  x: number;
  y: number;
  visible: boolean;
}

/** An annotation being created, before it is saved. */
export interface Draft {
  type: AnnotationType;
  start: number;
  end: number;
  /** marking: segment start set, waiting for the end; drawing: box/points on the frame; form: label etc. */
  stage: "marking" | "drawing" | "form";
  box?: Box;
  points?: Point[];
}

/** What a pointer on the picture does right now. */
export type DrawMode = { kind: "bbox" } | { kind: "keypoint" } | null;

export function normaliseBox(a: { x: number; y: number }, b: { x: number; y: number }): Box {
  const clamp = (v: number) => Math.min(1, Math.max(0, v));
  const x1 = clamp(Math.min(a.x, b.x));
  const y1 = clamp(Math.min(a.y, b.y));
  const x2 = clamp(Math.max(a.x, b.x));
  const y2 = clamp(Math.max(a.y, b.y));
  const r = (v: number) => Math.round(v * 10000) / 10000;
  return [r(x1), r(y1), r(Math.min(x2 - x1, 1 - x1)), r(Math.min(y2 - y1, 1 - y1))];
}
