"use client";

import { useCallback, useEffect, useRef, useState, type RefObject } from "react";
import { Player } from "@/components/inspector/Player";
import { TransportBar } from "@/components/inspector/TransportBar";
import type { VideoDetail } from "@/lib/api/types";
import { createFrameStore, type FrameStore } from "@/lib/inspector/frameStore";
import { actionFor } from "@/lib/inspector/shortcuts";
import { useFrameClock } from "@/lib/inspector/useFrameClock";
import { ObjectOverlay } from "./ObjectOverlay";
import { SkeletonOverlay } from "./SkeletonOverlay";

/**
 * The proxy with a hand run's skeletons and/or an object run's boxes on top, frame-exact, with the
 * inspector's transport and keys.
 */
export function RunPlayer({
  video,
  runId,
  objectRunId,
  highlightObject,
  startFrame,
  frameStore: external,
  seekRef,
}: {
  video: VideoDetail;
  /** Hand-tracking run whose skeletons to draw. */
  runId?: string | null;
  /** Object-detection run whose boxes to draw. */
  objectRunId?: string | null;
  highlightObject?: number | null;
  /** Frame to show once the frame clock is ready. */
  startFrame?: number;
  frameStore?: FrameStore;
  /** Receives the seek function, so a timeline beside the player can move it. */
  seekRef?: RefObject<((frame: number) => void) | null>;
}) {
  const clockState = useFrameClock(video);
  const clock = clockState.state === "loading" ? null : clockState.clock;
  const [own] = useState(() => createFrameStore(0));
  const frameStore = external ?? own;
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [playing, setPlaying] = useState(false);
  const [rate, setRate] = useState(1);
  const proxy = (video.derivatives?.proxy ?? {}) as { width?: number; height?: number };
  const aspect = proxy.width && proxy.height ? proxy.width / proxy.height : video.width && video.height ? video.width / video.height : 16 / 9;
  const fps = video.fps ?? 30;

  const seek = useCallback(
    (f: number) => {
      const v = videoRef.current;
      if (!v || !clock) return;
      const n = clock.clamp(f);
      v.currentTime = clock.seekTime(n);
      frameStore.set(n);
    },
    [clock, frameStore],
  );
  const step = useCallback((d: number) => {
    videoRef.current?.pause();
    seek(frameStore.get() + d);
  }, [seek, frameStore]);
  const toggle = useCallback(() => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) void v.play().catch(() => undefined);
    else v.pause();
  }, []);

  useEffect(() => {
    if (videoRef.current) videoRef.current.playbackRate = rate;
  }, [rate]);
  useEffect(() => {
    if (seekRef) seekRef.current = seek;
  }, [seek, seekRef]);
  const started = useRef(false);
  useEffect(() => {
    if (clock && startFrame != null && !started.current) {
      started.current = true;
      seek(startFrame);
    }
  }, [clock, startFrame, seek]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const a = actionFor(e);
      if (a === "togglePlay") toggle();
      else if (a === "prevFrame") step(-1);
      else if (a === "nextFrame") step(1);
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggle, step]);

  if (!video.proxy_url) return <p className="text-xs text-ink-3">This video has no playable proxy yet.</p>;
  return (
    <div className="flex flex-col gap-2">
      <div className="aspect-video w-full">
        <Player src={video.proxy_url} aspect={aspect} clock={clock} frameStore={frameStore} videoRef={videoRef} onPlayingChange={setPlaying}>
          {objectRunId ? <ObjectOverlay runId={objectRunId} frameStore={frameStore} highlight={highlightObject} /> : null}
          {runId ? <SkeletonOverlay runId={runId} frameStore={frameStore} aspect={aspect} /> : null}
        </Player>
      </div>
      <TransportBar
        playing={playing}
        frameStore={frameStore}
        frameCount={clock?.frameCount ?? video.frame_count ?? 0}
        fps={fps}
        rate={rate}
        onRate={setRate}
        onToggle={toggle}
        onStep={step}
        onEvent={() => undefined}
        onSeek={seek}
      />
      {clockState.state === "nominal" ? <p className="text-xs text-warning">No frame index: stepping uses the nominal {fps} fps.</p> : null}
    </div>
  );
}
