"use client";

import { Keyboard, X } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { ObjectOverlay } from "@/components/cv/ObjectOverlay";
import { SkeletonOverlay } from "@/components/cv/SkeletonOverlay";
import { EmptyState } from "@/components/ui";
import { browserApi } from "@/lib/api/browser";
import type { AdjacentEvent, AnnotationRead, AnnotationType, CvRunSummary, FrameIndex, JobRef, Page, VideoDetail } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { clockFromIndex, nominalClock, type FrameClock } from "@/lib/inspector/frames";
import { createFrameStore } from "@/lib/inspector/frameStore";
import { actionFor, SHORTCUTS, type InspectorAction } from "@/lib/inspector/shortcuts";
import type { Box, DrawMode, Point } from "@/lib/inspector/types";
import { followView, type View } from "@/lib/inspector/view";
import { AnnotationForm, TYPE_LABEL, type FormValues } from "./AnnotationForm";
import { AnnotationHistoryView } from "./AnnotationHistoryView";
import { AnnotationList } from "./AnnotationList";
import { FrameOverlay } from "./FrameOverlay";
import { InspectorTimeline } from "./InspectorTimeline";
import { Player } from "./Player";
import { TransportBar } from "./TransportBar";

/** Box/keypoint annotations are fetched for the overlay in windows of this many frames. */
const OVERLAY_CHUNK = 300;

type IndexState =
  | { state: "loading" }
  | { state: "exact"; clock: FrameClock }
  | { state: "nominal"; clock: FrameClock; reason: string };

interface DraftState {
  type: AnnotationType;
  /** marking: segment start set, waiting for the end; drawing: box/points on the picture; form: details. */
  stage: "marking" | "drawing" | "form";
  values: FormValues;
}

interface Toast {
  text: string;
  tone?: "error";
  undo?: () => void;
}

function valuesOf(a: AnnotationRead): FormValues {
  const data = a.data as { box?: Box; points?: Point[] };
  return {
    label: a.label,
    category: a.category,
    frame_start: a.frame_start,
    frame_end: a.frame_end,
    needs_review: a.needs_review,
    box: data.box,
    points: data.points,
  };
}

function dataFor(type: AnnotationType, v: FormValues): Record<string, unknown> {
  if (type === "bbox") return { box: v.box };
  if (type === "keypoint") return { points: v.points };
  return {};
}

const TOOLS: AnnotationType[] = ["segment", "bbox", "keypoint"];

export function Inspector({ video, canEdit, initialFrame }: { video: VideoDetail; canEdit: boolean; initialFrame?: number }) {
  const proxy = (video.derivatives?.proxy ?? {}) as { width?: number; height?: number; frame_count?: number; fps?: number };
  const fps = video.fps ?? proxy.fps ?? 30;
  const nominalCount = video.frame_count ?? proxy.frame_count ?? Math.max(1, Math.round((video.duration_s ?? 0) * fps));
  const aspect = (proxy.width && proxy.height ? proxy.width / proxy.height : video.width && video.height ? video.width / video.height : 16 / 9) || 16 / 9;

  const [index, setIndex] = useState<IndexState>({ state: "loading" });
  const clock = index.state === "loading" ? null : index.clock;
  const frameCount = clock?.frameCount || nominalCount;
  const [frameStore] = useState(() => createFrameStore(0));
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [playing, setPlaying] = useState(false);
  const [rate, setRate] = useState(1);
  const [view, setView] = useState<View>({ start: 0, end: Math.max(0, nominalCount - 1) });
  const [version, setVersion] = useState(0);
  const bump = () => setVersion((v) => v + 1);

  const [selected, setSelected] = useState<AnnotationRead | null>(null);
  const [edit, setEdit] = useState<FormValues | null>(null);
  const [draft, setDraft] = useState<DraftState | null>(null);
  const [draw, setDraw] = useState<DrawMode>(null);
  const [tool, setTool] = useState<AnnotationType>("segment");
  const [tab, setTab] = useState<"list" | "details" | "history">("list");
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [toast, setToast] = useState<Toast | null>(null);
  const [helpOpen, setHelpOpen] = useState(false);
  const [trackingRun, setTrackingRun] = useState<CvRunSummary | null>(null);
  const [objectRun, setObjectRun] = useState<CvRunSummary | null>(null);
  const [showSkeletons, setShowSkeletons] = useState(true);
  const [showObjects, setShowObjects] = useState(true);

  // The latest hand-tracking and object-detection runs for this video, for overlays.
  useEffect(() => {
    const ctrl = new AbortController();
    for (const [kind, setRun] of [["hand_tracking", setTrackingRun], ["object_detection", setObjectRun]] as const) {
      browserApi<Page<CvRunSummary>>("/cv/runs", { query: { video_id: video.id, kind, status: "succeeded", limit: 1 }, signal: ctrl.signal })
        .then((res) => res.ok && setRun(res.data.items[0] ?? null))
        .catch(() => undefined);
    }
    return () => ctrl.abort();
  }, [video.id]);

  // Frame index: exact per-frame timestamps. Without it, fall back to nominal FPS and say so.
  useEffect(() => {
    const ctrl = new AbortController();
    browserApi<FrameIndex>(`/videos/${video.id}/frame-index`, { signal: ctrl.signal })
      .then((res) => {
        const next: IndexState = res.ok
          ? { state: "exact", clock: clockFromIndex(res.data) }
          : { state: "nominal", clock: nominalClock(nominalCount, fps), reason: res.message };
        setIndex(next);
        const last = next.clock.frameCount - 1;
        setView((v) => (v.end > last || v.end === nominalCount - 1 ? { start: Math.min(v.start, last), end: last } : v));
      })
      .catch(() => undefined);
    return () => ctrl.abort();
  }, [video.id, nominalCount, fps]);

  useEffect(() => {
    if (videoRef.current) videoRef.current.playbackRate = rate;
  }, [rate]);

  useEffect(() => {
    if (!toast || toast.undo) return;
    const t = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(t);
  }, [toast]);

  // During playback, keep the playhead on screen.
  useEffect(() => {
    if (!playing) return;
    return frameStore.subscribe(() => setView((v) => followView(v, frameStore.get(), frameCount) ?? v));
  }, [playing, frameStore, frameCount]);

  // Box and keypoint annotations near the current frame, for the overlay.
  const chunk = useSyncExternalStore(
    frameStore.subscribe,
    () => Math.floor(frameStore.get() / OVERLAY_CHUNK),
    () => 0,
  );
  const [overlayItems, setOverlayItems] = useState<AnnotationRead[]>([]);
  useEffect(() => {
    const ctrl = new AbortController();
    const query = new URLSearchParams({ frame_from: String(chunk * OVERLAY_CHUNK), frame_to: String(chunk * OVERLAY_CHUNK + OVERLAY_CHUNK - 1), limit: "500" });
    query.append("type", "bbox");
    query.append("type", "keypoint");
    browserApi<Page<AnnotationRead>>(`/videos/${video.id}/annotations`, { query, signal: ctrl.signal })
      .then((res) => res.ok && setOverlayItems(res.data.items))
      .catch(() => undefined);
    return () => ctrl.abort();
  }, [video.id, chunk, version]);

  // --- playback -------------------------------------------------------------------------------------

  const seek = useCallback(
    (frame: number) => {
      const v = videoRef.current;
      if (!v || !clock) return;
      const n = clock.clamp(frame);
      v.currentTime = clock.seekTime(n);
      frameStore.set(n);
    },
    [clock, frameStore],
  );
  // Opened at a frame (e.g. from a movement event): go there once the frame clock is ready.
  const opened = useRef(false);
  useEffect(() => {
    if (!clock || initialFrame == null || opened.current) return;
    opened.current = true;
    seek(initialFrame);
  }, [clock, initialFrame, seek]);
  const step = useCallback(
    (delta: number) => {
      videoRef.current?.pause();
      seek(frameStore.get() + delta);
    },
    [seek, frameStore],
  );
  const toggle = useCallback(() => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) void v.play().catch(() => undefined);
    else v.pause();
  }, []);

  // --- selection and editing ------------------------------------------------------------------------

  const open = useCallback(
    (a: AnnotationRead, opts: { seek?: boolean; keepTab?: boolean } = {}) => {
      setSelected(a);
      setEdit(valuesOf(a));
      setDraft(null);
      setDraw(null);
      setFormError(null);
      if (!opts.keepTab) setTab((t) => (t === "history" ? "history" : "details"));
      const f = frameStore.get();
      if (opts.seek && (f < a.frame_start || f > a.frame_end)) seek(a.frame_start);
    },
    [frameStore, seek],
  );

  const select = useCallback(
    async (id: string, opts: { seek?: boolean } = {}) => {
      const res = await browserApi<AnnotationRead>(`/annotations/${id}`);
      if (res.ok) open(res.data, opts);
      else setToast({ text: res.message, tone: "error" });
    },
    [open],
  );

  const deselect = () => {
    setSelected(null);
    setEdit(null);
    setDraw(null);
    setFormError(null);
    setTab("list");
  };

  const startCreate = () => {
    if (!canEdit) return setToast({ text: "Your role can view annotations but not change them." });
    const f = frameStore.get();
    if (draft?.stage === "marking") {
      const start = Math.min(draft.values.frame_start, f);
      const end = Math.max(draft.values.frame_start, f);
      setDraft({ ...draft, stage: "form", values: { ...draft.values, frame_start: start, frame_end: end } });
      setToast({ text: `Segment f${start}–f${end}. Add a label and save.` });
      return;
    }
    if (draft?.stage === "drawing" && draft.type === "keypoint") {
      if (draft.values.points?.length) {
        setDraft({ ...draft, stage: "form" });
        setDraw(null);
      }
      return;
    }
    if (draft?.stage === "form") {
      // A again while the form is open extends the range to the current frame.
      const v = draft.values;
      setDraft({ ...draft, values: f >= v.frame_start ? { ...v, frame_end: f } : { ...v, frame_start: f } });
      return;
    }
    videoRef.current?.pause();
    setSelected(null);
    setEdit(null);
    setFormError(null);
    setTab("details");
    const values: FormValues = { label: "", category: "general", frame_start: f, frame_end: f, needs_review: false };
    if (tool === "segment") {
      setDraft({ type: "segment", stage: "marking", values });
      setToast({ text: `Segment starts at f${f}. Go to its last frame and press A again.` });
    } else {
      setDraft({ type: tool, stage: "drawing", values: tool === "keypoint" ? { ...values, points: [] } : values });
      setDraw({ kind: tool === "bbox" ? "bbox" : "keypoint" });
      setToast({ text: tool === "bbox" ? "Drag on the picture to draw the box." : "Click on the picture to place points, then press A or Done." });
    }
  };

  const onBoxDrawn = (box: Box) => {
    setDraw(null);
    if (draft) setDraft({ ...draft, stage: "form", values: { ...draft.values, box } });
    else if (edit) setEdit({ ...edit, box });
  };

  const onPointAdded = (p: { x: number; y: number }) => {
    const add = (points: Point[] = []) => {
      const used = new Set(points.map((q) => q.name));
      let n = points.length + 1;
      while (used.has(`p${n}`)) n++;
      return [...points, { name: `p${n}`, x: Math.round(p.x * 10000) / 10000, y: Math.round(p.y * 10000) / 10000, visible: true }];
    };
    if (draft) setDraft({ ...draft, values: { ...draft.values, points: add(draft.values.points) } });
    else if (edit) setEdit({ ...edit, points: add(edit.points) });
  };

  const saveDraft = async (values: FormValues) => {
    if (!draft) return;
    setBusy(true);
    const res = await browserApi<AnnotationRead>(`/videos/${video.id}/annotations`, {
      method: "POST",
      body: {
        type: draft.type,
        label: values.label,
        category: values.category,
        frame_start: values.frame_start,
        frame_end: values.frame_end,
        needs_review: values.needs_review,
        data: dataFor(draft.type, values),
      },
    });
    setBusy(false);
    if (!res.ok) return setFormError(res.message);
    open(res.data);
    bump();
    setToast({ text: `Saved “${res.data.label}”` });
  };

  const saveEdit = async (values: FormValues) => {
    if (!selected) return;
    setBusy(true);
    const body: Record<string, unknown> = {
      label: values.label,
      category: values.category,
      frame_start: values.frame_start,
      frame_end: values.frame_end,
      needs_review: values.needs_review,
      revision: selected.revision,
    };
    if (selected.type !== "segment") body.data = dataFor(selected.type, values);
    const res = await browserApi<AnnotationRead>(`/annotations/${selected.id}`, { method: "PATCH", body });
    setBusy(false);
    if (!res.ok) {
      setFormError(res.kind === "http" && res.status === 409 ? `${res.message}. Reopen it to see the latest version.` : res.message);
      return;
    }
    const corrected = res.data.id !== selected.id;
    open(res.data, { keepTab: true });
    bump();
    setToast({ text: corrected ? "Saved as a human correction. The AI prediction is kept in history." : "Saved" });
  };

  const toggleReview = async () => {
    if (!selected || !canEdit) return;
    const res = await browserApi<AnnotationRead>(`/annotations/${selected.id}`, {
      method: "PATCH",
      body: { needs_review: !selected.needs_review, revision: selected.revision },
    });
    if (!res.ok) return setToast({ text: res.message, tone: "error" });
    open(res.data, { keepTab: true });
    bump();
    setToast({ text: res.data.needs_review ? `“${res.data.label}” marked for review` : "Review mark removed" });
  };

  const restore = useCallback(
    async (id: string) => {
      const res = await browserApi<AnnotationRead>(`/annotations/${id}/restore`, { method: "POST" });
      if (!res.ok) return setToast({ text: res.message, tone: "error" });
      open(res.data);
      bump();
      setToast({ text: `Restored “${res.data.label}”` });
    },
    [open],
  );

  const remove = async () => {
    if (!selected || !canEdit) return;
    const target = selected;
    const res = await browserApi<AnnotationRead>(`/annotations/${target.id}`, { method: "DELETE" });
    if (!res.ok) return setToast({ text: res.message, tone: "error" });
    deselect();
    bump();
    setToast({ text: `Deleted “${target.label}”. It stays in history.`, undo: () => void restore(target.id) });
  };

  const jump = async (direction: "prev" | "next") => {
    const res = await browserApi<AdjacentEvent>(`/videos/${video.id}/annotations/adjacent`, { query: { frame: frameStore.get(), direction } });
    if (!res.ok) return setToast({ text: res.message, tone: "error" });
    if (res.data.frame == null) return setToast({ text: direction === "next" ? "No annotations after this frame" : "No annotations before this frame" });
    videoRef.current?.pause();
    seek(res.data.frame);
    if (res.data.annotation_id) void select(res.data.annotation_id);
  };

  const cancel = () => {
    if (helpOpen) return setHelpOpen(false);
    if (draw) {
      setDraw(null);
      if (draft?.stage === "drawing" && !draft.values.box && !draft.values.points?.length) setDraft(null);
      else if (draft?.stage === "drawing") setDraft({ ...draft, stage: "form" });
      return;
    }
    if (draft) return setDraft(null);
    if (selected) deselect();
  };

  const rebuildIndex = async () => {
    const res = await browserApi<JobRef>(`/videos/${video.id}/frame-index`, { method: "POST" });
    setToast(res.ok ? { text: "Building the frame index. Reload this page in a minute." } : { text: res.message, tone: "error" });
  };

  // --- keyboard -------------------------------------------------------------------------------------

  const handle = (action: InspectorAction) => {
    switch (action) {
      case "togglePlay":
        return toggle();
      case "prevFrame":
        return step(-1);
      case "nextFrame":
        return step(1);
      case "prevEvent":
        return void jump("prev");
      case "nextEvent":
        return void jump("next");
      case "create":
        return startCreate();
      case "review":
        return void toggleReview();
      case "delete":
        return void remove();
      case "cancel":
        return cancel();
      case "help":
        return setHelpOpen((o) => !o);
    }
  };
  const handler = useRef(handle);
  useEffect(() => {
    handler.current = handle;
  });
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const action = actionFor(e);
      if (!action) return;
      e.preventDefault();
      handler.current(action);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // --- render ---------------------------------------------------------------------------------------

  const pending = useMemo(() => (draft && draft.stage !== "drawing" ? { start: draft.values.frame_start, end: draft.values.frame_end } : null), [draft]);
  const currentFrame = useCallback(() => frameStore.get(), [frameStore]);
  const onTimelineSelect = useCallback((id: string) => void select(id), [select]);
  const draftGeometry = draft ?? (edit && selected && draw ? { values: edit } : null);

  if (!video.proxy_url) {
    return (
      <EmptyState
        title={video.status === "corrupt" ? "This file couldn't be read" : "Preparing playback"}
        description={video.status === "corrupt" ? (video.error ?? undefined) : "The proxy video is still being generated. Reload in a moment."}
      />
    );
  }

  return (
    <div className="flex flex-col gap-3" data-testid="inspector">
      <div className="flex flex-wrap items-center gap-2">
        <div className="min-w-0 flex-1">
          <div className="text-xs text-ink-3">
            <Link href="/annotation/inspector" className="hover:text-ink">Video Inspector</Link>
            {video.session ? (
              <>
                {" / "}
                <Link href={`/data/sessions/${video.session.id}`} className="font-mono hover:text-ink">{video.session.name}</Link>
              </>
            ) : null}
          </div>
          <h1 className="truncate text-lg font-bold tracking-tight">
            <Link href={`/data/videos/${video.id}`} className="hover:underline">{video.original_filename}</Link>
          </h1>
        </div>
        <span
          data-testid="frame-index-state"
          data-state={index.state}
          className={cn(
            "inline-flex h-[22px] items-center rounded border px-1.5 text-[11.5px] font-semibold",
            index.state === "exact" ? "border-success-line bg-success-bg text-success" : index.state === "nominal" ? "border-warning-line bg-warning-bg text-warning" : "border-line text-ink-3",
          )}
          title={index.state === "exact" ? "Seeking uses each frame's real timestamp" : undefined}
        >
          {index.state === "exact" ? "Frame-exact" : index.state === "nominal" ? "Approximate seeking" : "Loading frame index…"}
        </span>
        <button
          type="button"
          onClick={() => setHelpOpen(true)}
          className="inline-flex h-8 items-center gap-1.5 rounded-md border border-line px-2.5 text-xs font-semibold hover:bg-hover"
        >
          <Keyboard className="size-3.5" aria-hidden /> Shortcuts
        </button>
      </div>

      {index.state === "nominal" ? (
        <div className="flex flex-wrap items-center gap-2 rounded-md border border-warning-line bg-warning-bg px-3 py-2 text-xs text-warning">
          <span>
            This video has no frame index ({index.reason}). Frame stepping uses the nominal {fps} fps and may be off for variable frame rate video.
          </span>
          {canEdit ? (
            <button type="button" onClick={rebuildIndex} className="font-semibold underline">Build frame index</button>
          ) : null}
        </div>
      ) : null}

      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(300px,360px)]">
        <div className="flex min-w-0 flex-col gap-2">
          <div className="aspect-video w-full lg:aspect-auto lg:h-[min(48vh,540px)] lg:min-h-[220px]">
            <Player src={video.proxy_url} aspect={aspect} clock={clock} frameStore={frameStore} videoRef={videoRef} onPlayingChange={setPlaying}>
              {objectRun && showObjects ? <ObjectOverlay runId={objectRun.id} frameStore={frameStore} /> : null}
              {trackingRun && showSkeletons ? <SkeletonOverlay runId={trackingRun.id} frameStore={frameStore} aspect={aspect} /> : null}
              <FrameOverlay
                frameStore={frameStore}
                annotations={overlayItems}
                selectedId={selected?.id ?? null}
                onSelect={(id) => void select(id)}
                draftBox={draftGeometry?.values.box}
                draftPoints={draftGeometry?.values.points}
                draw={draw}
                onBoxDrawn={onBoxDrawn}
                onPointAdded={onPointAdded}
              />
            </Player>
          </div>
          <TransportBar
            playing={playing}
            frameStore={frameStore}
            frameCount={frameCount}
            fps={fps}
            rate={rate}
            onRate={setRate}
            onToggle={toggle}
            onStep={step}
            onEvent={(d) => void jump(d)}
            onSeek={seek}
          />
          {trackingRun || objectRun ? (
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-2">
              {trackingRun ? (
                <label className="flex items-center gap-1.5">
                  <input type="checkbox" checked={showSkeletons} onChange={(e) => setShowSkeletons(e.target.checked)} />
                  Hand skeletons from{" "}
                  <Link href={`/cv/hands/${trackingRun.id}`} className="font-medium underline">
                    {trackingRun.model_version?.name ?? "the latest run"}
                  </Link>
                </label>
              ) : null}
              {objectRun ? (
                <label className="flex items-center gap-1.5">
                  <input type="checkbox" checked={showObjects} onChange={(e) => setShowObjects(e.target.checked)} />
                  Object boxes from{" "}
                  <Link href={`/cv/objects/${objectRun.id}`} className="font-medium underline">
                    {objectRun.model_version?.name ?? "the latest run"}
                  </Link>
                </label>
              ) : null}
            </div>
          ) : null}
          {canEdit ? (
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="text-ink-3">New</span>
              <div className="flex overflow-hidden rounded-md border border-line" role="radiogroup" aria-label="Annotation type">
                {TOOLS.map((t) => (
                  <button
                    key={t}
                    type="button"
                    role="radio"
                    aria-checked={tool === t}
                    onClick={() => setTool(t)}
                    className={cn("h-7 px-2.5 font-medium", tool === t ? "bg-ink text-canvas" : "hover:bg-hover")}
                  >
                    {TYPE_LABEL[t]}
                  </button>
                ))}
              </div>
              <button type="button" onClick={startCreate} className="h-7 rounded-md border border-line px-2.5 font-semibold hover:bg-hover">
                {draft?.stage === "marking" ? "Set end here (A)" : draft?.stage === "drawing" && draft.type === "keypoint" ? "Done placing points (A)" : "Create (A)"}
              </button>
              {draw ? (
                <button type="button" onClick={cancel} className="h-7 rounded-md px-2 font-medium text-ink-2 hover:bg-hover">
                  Stop drawing (Esc)
                </button>
              ) : null}
            </div>
          ) : null}
        </div>

        <aside className="flex min-h-[320px] min-w-0 flex-col overflow-hidden rounded-lg border border-line lg:h-[calc(min(48vh,540px)+84px)]">
          <div className="flex border-b border-line text-xs font-semibold" role="tablist">
            {(["list", "details", "history"] as const).map((t) => (
              <button
                key={t}
                type="button"
                role="tab"
                aria-selected={tab === t}
                disabled={t === "history" && !selected}
                onClick={() => setTab(t)}
                className={cn("flex-1 px-3 py-2.5 disabled:text-ink-3", tab === t ? "border-b-2 border-ink" : "text-ink-2 hover:bg-hover")}
              >
                {t === "list" ? "Annotations" : t === "details" ? (draft ? "New" : "Details") : "History"}
              </button>
            ))}
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-3">
            {tab === "list" ? (
              <AnnotationList
                videoId={video.id}
                view={view}
                version={version}
                selectedId={selected?.id ?? null}
                canEdit={canEdit}
                onSelect={(a) => open(a, { seek: true })}
                onRestore={(a) => void restore(a.id)}
              />
            ) : null}
            {tab === "details" ? (
              draft && draft.stage !== "drawing" ? (
                draft.stage === "marking" ? (
                  <p className="text-xs text-ink-2">
                    Segment starts at <span className="font-mono">f{draft.values.frame_start}</span>. Move to its last frame and press <kbd className="rounded border border-line px-1 font-mono">A</kbd> again.
                  </p>
                ) : (
                  <AnnotationForm
                    mode="create"
                    type={draft.type}
                    values={draft.values}
                    frameCount={frameCount}
                    currentFrame={currentFrame}
                    canEdit={canEdit}
                    busy={busy}
                    error={formError}
                    onChange={(values) => setDraft({ ...draft, values })}
                    onSubmit={(v) => void saveDraft(v)}
                    onCancel={() => setDraft(null)}
                    onRedraw={draft.type === "segment" ? undefined : () => setDraw({ kind: draft.type === "bbox" ? "bbox" : "keypoint" })}
                  />
                )
              ) : draft ? (
                <p className="text-xs text-ink-2">
                  {draft.type === "bbox" ? "Drag on the picture to draw the box." : `Click on the picture to place points (${draft.values.points?.length ?? 0} so far), then press A.`}
                </p>
              ) : selected && edit ? (
                <AnnotationForm
                  key={selected.id}
                  mode="edit"
                  type={selected.type}
                  values={edit}
                  annotation={selected}
                  frameCount={frameCount}
                  currentFrame={currentFrame}
                  canEdit={canEdit && !selected.deleted_at && !selected.superseded_at}
                  busy={busy}
                  error={formError}
                  onChange={setEdit}
                  onSubmit={(v) => void saveEdit(v)}
                  onCancel={deselect}
                  onRedraw={selected.type === "segment" ? undefined : () => setDraw({ kind: selected.type === "bbox" ? "bbox" : "keypoint" })}
                />
              ) : (
                <p className="text-xs text-ink-3">Select an annotation on the timeline or in the list{canEdit ? ", or press A to create one" : ""}.</p>
              )
            ) : null}
            {tab === "history" && selected ? <AnnotationHistoryView annotationId={selected.id} version={version} onOpen={(id) => void select(id, { seek: true })} /> : null}
          </div>
        </aside>
      </div>

      <InspectorTimeline
        videoId={video.id}
        frameCount={frameCount}
        fps={fps}
        view={view}
        onViewChange={setView}
        frameStore={frameStore}
        onSeek={seek}
        selectedId={selected?.id ?? null}
        onSelect={onTimelineSelect}
        version={version}
        pending={pending}
        canEdit={canEdit}
      />

      {toast ? (
        <div
          role="status"
          className={cn(
            "fixed bottom-4 left-1/2 z-50 flex max-w-[92vw] -translate-x-1/2 items-center gap-3 rounded-md border px-3 py-2 text-xs shadow-lg",
            toast.tone === "error" ? "border-error-line bg-error-bg text-error" : "border-line bg-canvas",
          )}
        >
          <span>{toast.text}</span>
          {toast.undo ? (
            <button
              type="button"
              className="font-semibold underline"
              onClick={() => {
                toast.undo?.();
                setToast(null);
              }}
            >
              Undo
            </button>
          ) : null}
          <button type="button" aria-label="Dismiss" onClick={() => setToast(null)} className="text-ink-3 hover:text-ink">
            <X className="size-3.5" aria-hidden />
          </button>
        </div>
      ) : null}

      {helpOpen ? (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/30 p-4" onClick={() => setHelpOpen(false)}>
          <div role="dialog" aria-label="Keyboard shortcuts" className="w-full max-w-md rounded-lg border border-line bg-canvas p-4 shadow-xl" onClick={(e) => e.stopPropagation()}>
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-bold">Keyboard shortcuts</h2>
              <button type="button" aria-label="Close" onClick={() => setHelpOpen(false)} className="grid size-7 place-items-center rounded-md hover:bg-hover">
                <X className="size-4" aria-hidden />
              </button>
            </div>
            <dl className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-x-4 gap-y-2 text-xs">
              {SHORTCUTS.map((s) => (
                <div key={s.label} className="contents">
                  <dt className="flex gap-1">
                    {s.keys.map((k) => (
                      <kbd key={k} className="rounded border border-line-strong bg-subtle px-1.5 py-0.5 font-mono text-[11px]">{k}</kbd>
                    ))}
                  </dt>
                  <dd className="text-ink-2">{s.label}</dd>
                </div>
              ))}
            </dl>
          </div>
        </div>
      ) : null}
    </div>
  );
}
