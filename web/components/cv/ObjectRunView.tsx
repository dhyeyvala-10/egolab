"use client";

import { useMemo, useRef, useState } from "react";
import { ConfidenceBadge, DataTable, Timeline, TimelinePlayhead, type Column, type TimelineTrack } from "@/components/ui";
import type { CvRunDetail, ObjectTrackRead, VideoDetail } from "@/lib/api/types";
import { createFrameStore, useFrame, type FrameStore } from "@/lib/inspector/frameStore";
import { RunPlayer } from "./RunPlayer";

const fmt = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

function Playhead({ frameStore, end }: { frameStore: FrameStore; end: number }) {
  return <TimelinePlayhead frame={useFrame(frameStore)} view={{ start: 0, end }} />;
}

/** Player with an object run's boxes (and the video's hand skeletons), a track per object, and the tracks table. */
export function ObjectRunView({ run, video, handRunId }: { run: CvRunDetail; video: VideoDetail; handRunId?: string | null }) {
  const [frameStore] = useState(() => createFrameStore(0));
  const seekRef = useRef<((frame: number) => void) | null>(null);
  const [focus, setFocus] = useState<number | null>(null);
  const frameCount = run.frames_total ?? video.frame_count ?? 1;

  const tracks: TimelineTrack[] = useMemo(
    () =>
      run.object_tracks.map((t) => ({
        id: `o${t.track_id}`,
        label: `${t.label} #${t.track_id}`,
        kind: "ai" as const,
        total: t.frames_detected,
        segments: [{ id: `o${t.track_id}`, start: t.first_frame, end: t.last_frame, label: `${fmt.format(t.frames_detected)} frames`, confidence: t.mean_score }],
      })),
    [run.object_tracks],
  );

  const columns: Column<ObjectTrackRead>[] = [
    { key: "track_id", header: "Track", cell: (t) => <span className="font-mono text-xs">#{t.track_id}</span> },
    { key: "label", header: "Object", cell: (t) => <span className="font-medium">{t.label}</span> },
    {
      key: "first_frame",
      header: "Frames",
      cell: (t) => (
        <button type="button" className="font-mono text-xs hover:underline" onClick={(e) => { e.stopPropagation(); setFocus(t.track_id); seekRef.current?.(t.first_frame); }}>
          f{t.first_frame}–f{t.last_frame}
        </button>
      ),
    },
    { key: "frames_detected", header: "Detected", align: "right", cell: (t) => fmt.format(t.frames_detected) },
    { key: "missing_detections", header: "Missing", align: "right", cell: (t) => fmt.format(t.missing_detections) },
    { key: "mean_score", header: "Mean score", cell: (t) => <ConfidenceBadge value={t.mean_score} modelVersion={run.model_version?.version} /> },
    { key: "max_score", header: "Best", align: "right", cell: (t) => t.max_score.toFixed(2) },
    { key: "path_length_px", header: "Moved", align: "right", cell: (t) => `${fmt.format(t.path_length_px)} px` },
  ];

  return (
    <div className="flex flex-col gap-4">
      <RunPlayer video={video} runId={handRunId} objectRunId={run.id} highlightObject={focus} frameStore={frameStore} seekRef={seekRef} />
      <Timeline
        tracks={tracks.length ? tracks : [{ id: "none", label: "Objects", kind: "ai", total: 0, segments: [], emptyHint: "No objects were detected" }]}
        frameCount={frameCount}
        fps={video.fps ?? 30}
        onSeek={(f) => seekRef.current?.(f)}
        onSegmentClick={(s) => { setFocus(Number(s.id.slice(1))); seekRef.current?.(s.start); }}
        overlay={<Playhead frameStore={frameStore} end={frameCount - 1} />}
      />
      <DataTable
        columns={columns}
        rows={run.object_tracks}
        rowKey={(t) => String(t.track_id)}
        onRowClick={(t) => { setFocus(focus === t.track_id ? null : t.track_id); seekRef.current?.(t.first_frame); }}
        caption="Object tracks"
        empty={<p className="px-4 py-6 text-center text-xs text-ink-3">No objects were detected in this video.</p>}
      />
    </div>
  );
}
