/** The timeline's visible frame window, inclusive. */
export interface View {
  start: number;
  end: number;
}

/** Narrowest zoom: this many frames across the timeline. */
export const MIN_SPAN = 20;

/** Scale the window by `factor` (< 1 zooms in) keeping `anchor` at the same place on screen. */
export function zoomView(view: View, factor: number, anchor: number, frameCount: number): View {
  const span = view.end - view.start + 1;
  const next = Math.round(Math.min(frameCount, Math.max(Math.min(MIN_SPAN, frameCount), span * factor)));
  const a = Math.min(Math.max(anchor, view.start), view.end);
  const start = Math.round(a - ((a - view.start) / span) * next);
  return clampView(start, next, frameCount);
}

/** Move the window by `delta` frames, keeping its size. */
export function panView(view: View, delta: number, frameCount: number): View {
  return clampView(view.start + delta, view.end - view.start + 1, frameCount);
}

/** During playback, page the window forward (or back) so the playhead stays visible. */
export function followView(view: View, frame: number, frameCount: number): View | null {
  if (frame >= view.start && frame <= view.end) return null;
  const span = view.end - view.start + 1;
  return clampView(frame - Math.floor(span * 0.05), span, frameCount);
}

function clampView(start: number, span: number, frameCount: number): View {
  const s = Math.min(Math.max(0, start), Math.max(0, frameCount - span));
  return { start: s, end: Math.min(frameCount - 1, s + span - 1) };
}
