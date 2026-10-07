import { useSyncExternalStore } from "react";

/**
 * The current frame lives outside React state: it changes up to 60 times a second during playback, and
 * only the few components that show it (frame counter, playhead, overlays) should re-render.
 */
export interface FrameStore {
  get(): number;
  set(frame: number): void;
  subscribe(listener: () => void): () => void;
}

export function createFrameStore(initial = 0): FrameStore {
  let frame = initial;
  const listeners = new Set<() => void>();
  return {
    get: () => frame,
    set(next) {
      if (next === frame) return;
      frame = next;
      for (const l of listeners) l();
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}

export function useFrame(store: FrameStore): number {
  return useSyncExternalStore(store.subscribe, store.get, store.get);
}
