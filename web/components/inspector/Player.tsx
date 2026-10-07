"use client";

import { useEffect, useState, type ReactNode, type RefObject } from "react";
import type { FrameClock } from "@/lib/inspector/frames";
import type { FrameStore } from "@/lib/inspector/frameStore";

/** Largest box of the given aspect ratio that fits in the container, centred (like object-fit: contain). */
function fit(container: { width: number; height: number }, aspect: number) {
  if (!container.width || !container.height || !aspect) return { width: 0, height: 0 };
  const width = Math.min(container.width, container.height * aspect);
  return { width, height: width / aspect };
}

/**
 * The proxy video, sized to its aspect ratio so overlays can use frame-normalised coordinates.
 *
 * The frame number shown everywhere comes from the frame the browser actually presents
 * (`requestVideoFrameCallback` → media time → frame index), not from the frame we asked for.
 */
export function Player({
  src,
  aspect,
  clock,
  frameStore,
  videoRef,
  onPlayingChange,
  children,
}: {
  src: string;
  aspect: number;
  clock: FrameClock | null;
  frameStore: FrameStore;
  videoRef: RefObject<HTMLVideoElement | null>;
  onPlayingChange: (playing: boolean) => void;
  /** Overlays, absolutely positioned over the picture. */
  children?: ReactNode;
}) {
  const [box, setBox] = useState<HTMLDivElement | null>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });

  useEffect(() => {
    if (!box) return;
    const measure = () => setSize({ width: box.clientWidth, height: box.clientHeight });
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(box);
    return () => ro.disconnect();
  }, [box]);

  useEffect(() => {
    const v = videoRef.current;
    if (!v || !clock) return;
    let handle = 0;
    let stopped = false;
    const report = () => frameStore.set(clock.frameAt(v.currentTime));
    const rvfc = typeof v.requestVideoFrameCallback === "function";
    if (rvfc) {
      const onFrame: VideoFrameRequestCallback = (_now, meta) => {
        frameStore.set(clock.frameAt(meta.mediaTime));
        if (!stopped) handle = v.requestVideoFrameCallback(onFrame);
      };
      handle = v.requestVideoFrameCallback(onFrame);
    } else {
      v.addEventListener("timeupdate", report);
    }
    v.addEventListener("seeked", report);
    return () => {
      stopped = true;
      if (rvfc) v.cancelVideoFrameCallback(handle);
      else v.removeEventListener("timeupdate", report);
      v.removeEventListener("seeked", report);
    };
  }, [clock, frameStore, videoRef]);

  const fitted = fit(size, aspect);

  return (
    <div ref={setBox} className="relative h-full min-h-0 w-full overflow-hidden rounded-lg bg-ink">
      <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2" style={{ width: fitted.width, height: fitted.height }}>
        <video
          ref={videoRef}
          src={src}
          preload="auto"
          playsInline
          muted
          data-testid="inspector-video"
          className="block size-full"
          onPlay={() => onPlayingChange(true)}
          onPause={() => onPlayingChange(false)}
          onEnded={() => onPlayingChange(false)}
        />
        {children}
      </div>
    </div>
  );
}
