"use client";

import { useMemo, useRef, useState } from "react";
import { ConfidenceBadge, DataTable, Timeline, TimelinePlayhead, type Column, type TimelineTrack } from "@/components/ui";
import type { CvRunDetail, HandTrackRead, VideoDetail } from "@/lib/api/types";
import { createFrameStore, useFrame, type FrameStore } from "@/lib/inspector/frameStore";
import { RunPlayer } from "./RunPlayer";

const fmt = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

function Playhead({ frameStore, end }: { frameStore: FrameStore; end: number }) {
  return <TimelinePlayhead frame={useFrame(frameStore)} view={{ start: 0, end }} />;
}

interface Failure {
  frame: number;
  lost_track_id: number;
  new_track_id: number;
  handedness: string;
  gap_frames: number;
}

/** Player with skeletons, the run's presence timeline (tracks, gaps, failures), and the tracks table. */
export function HandRunView({ run, video }: { run: CvRunDetail; video: VideoDetail }) {
  const [frameStore] = useState(() => createFrameStore(0));
  const seekRef = useRef<((frame: number) => void) | null>(null);
  const frameCount = run.frames_total ?? video.frame_count ?? 1;
  const fps = video.fps ?? 30;
  const failures = useMemo(() => (run.stats.failures ?? []) as Failure[], [run.stats]);
  const noHand = useMemo(() => (run.stats.no_hand_ranges ?? []) as [number, number][], [run.stats]);

  const tracks: TimelineTrack[] = useMemo(
    () => [
      ...run.hand_tracks.map((t) => ({
        id: `t${t.track_id}`,
        label: `${t.handedness === "left" ? "Left" : "Right"} hand #${t.track_id}`,
        kind: "ai" as const,
        total: t.frames_detected,
        segments: [{ id: `t${t.track_id}`, start: t.first_frame, end: t.last_frame, label: `${fmt.format(t.frames_detected)} frames`, confidence: t.mean_confidence }],
      })),
      {
        id: "none",
        label: "No hand detected",
        kind: "neutral" as const,
        total: noHand.reduce((n, [a, b]) => n + (b - a + 1), 0),
        segments: noHand.map(([a, b]) => ({ id: `n${a}`, start: a, end: b })),
        emptyHint: "A hand was found in every processed frame",
      },
      {
        id: "failures",
        label: "Tracking failures",
        kind: "event" as const,
        total: failures.length,
        segments: failures.map((f) => ({ id: `f${f.frame}`, start: f.frame, end: f.frame, label: `#${f.lost_track_id} → #${f.new_track_id}` })),
        emptyHint: "No hand was dropped and re-acquired",
      },
    ],
    [run.hand_tracks, noHand, failures],
  );

  const columns: Column<HandTrackRead>[] = [
    { key: "track_id", header: "Track", cell: (t) => <span className="font-mono text-xs">#{t.track_id}</span> },
    { key: "handedness", header: "Hand", cell: (t) => (t.handedness === "left" ? "Left" : "Right") },
    {
      key: "first_frame",
      header: "Frames",
      cell: (t) => (
        <button type="button" className="font-mono text-xs hover:underline" onClick={() => seekRef.current?.(t.first_frame)}>
          f{t.first_frame}–f{t.last_frame}
        </button>
      ),
    },
    { key: "frames_detected", header: "Detected", align: "right", cell: (t) => fmt.format(t.frames_detected) },
    { key: "missing_detections", header: "Missing", align: "right", cell: (t) => fmt.format(t.missing_detections) },
    { key: "mean_confidence", header: "Confidence", cell: (t) => <ConfidenceBadge value={t.mean_confidence} modelVersion={run.model_version?.version} /> },
    { key: "mean_speed_px_s", header: "Mean wrist speed", align: "right", cell: (t) => `${fmt.format(t.mean_speed_px_s)} px/s` },
    { key: "peak_speed_px_s", header: "Peak", align: "right", cell: (t) => `${fmt.format(t.peak_speed_px_s)} px/s` },
    { key: "path_length_px", header: "Path", align: "right", cell: (t) => `${fmt.format(t.path_length_px)} px` },
  ];

  return (
    <div className="flex flex-col gap-4">
      <RunPlayer video={video} runId={run.id} frameStore={frameStore} seekRef={seekRef} />
      <Timeline
        tracks={tracks}
        frameCount={frameCount}
        fps={fps}
        onSeek={(f) => seekRef.current?.(f)}
        onSegmentClick={(s) => seekRef.current?.(s.start)}
        overlay={<Playhead frameStore={frameStore} end={frameCount - 1} />}
      />
      <DataTable columns={columns} rows={run.hand_tracks} rowKey={(t) => String(t.track_id)} caption="Hand tracks" empty={<p className="px-4 py-6 text-center text-xs text-ink-3">No hands were detected in this video.</p>} />
    </div>
  );
}
