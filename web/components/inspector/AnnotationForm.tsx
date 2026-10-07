"use client";

import { Crosshair, Trash2 } from "lucide-react";
import { useEffect, useId, useState, type FormEvent } from "react";
import { ConfidenceBadge, SourceBadge } from "@/components/ui";
import type { AnnotationCategory, AnnotationRead, AnnotationType, LabelCount } from "@/lib/api/types";
import { browserApi } from "@/lib/api/browser";
import type { Box, Point } from "@/lib/inspector/types";
import { inputClass } from "@/components/data/Field";

export const CATEGORIES: { value: AnnotationCategory; label: string }[] = [
  { value: "general", label: "General" },
  { value: "hand", label: "Hand" },
  { value: "finger", label: "Finger" },
  { value: "object", label: "Object interaction" },
  { value: "movement", label: "Movement" },
];

export const TYPE_LABEL: Record<AnnotationType, string> = { segment: "Segment", bbox: "Bounding box", keypoint: "Keypoints" };

export interface FormValues {
  label: string;
  category: AnnotationCategory;
  frame_start: number;
  frame_end: number;
  needs_review: boolean;
  box?: Box;
  points?: Point[];
}

/** Label suggestions from labels already in use. */
function useLabels(): LabelCount[] {
  const [labels, setLabels] = useState<LabelCount[]>([]);
  useEffect(() => {
    const ctrl = new AbortController();
    browserApi<LabelCount[]>("/annotations/labels", { query: { limit: 50 }, signal: ctrl.signal })
      .then((res) => res.ok && setLabels(res.data))
      .catch(() => undefined);
    return () => ctrl.abort();
  }, []);
  return labels;
}

const fmt = (v: number) => v.toFixed(3);

/**
 * Create or edit one annotation. Frame fields have "use current frame" buttons; geometry is drawn on the
 * picture and shown here as numbers.
 */
export function AnnotationForm({
  mode,
  type,
  values: v,
  annotation,
  frameCount,
  currentFrame,
  canEdit,
  busy,
  error,
  onSubmit,
  onCancel,
  onRedraw,
  onChange,
}: {
  mode: "create" | "edit";
  type: AnnotationType;
  values: FormValues;
  annotation?: AnnotationRead;
  frameCount: number;
  currentFrame: () => number;
  canEdit: boolean;
  busy: boolean;
  error: string | null;
  onSubmit: (values: FormValues) => void;
  onCancel: () => void;
  /** Start drawing the box / points again on the picture. */
  onRedraw?: () => void;
  /** Controlled: the parent keeps the values (geometry is drawn on the picture it owns). */
  onChange: (values: FormValues) => void;
}) {
  const id = useId();
  const labels = useLabels();
  const set = (patch: Partial<FormValues>) => onChange({ ...v, ...patch });
  const last = frameCount - 1;
  const rangeError = v.frame_end < v.frame_start ? "End must be at or after start" : v.frame_end > last ? `Last frame is ${last}` : null;
  const geometryMissing = (type === "bbox" && !v.box) || (type === "keypoint" && !v.points?.length);
  const readOnly = !canEdit;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (rangeError || geometryMissing || !v.label.trim()) return;
    onSubmit({ ...v, label: v.label.trim() });
  };

  return (
    <form onSubmit={submit} className="flex flex-col gap-3" aria-label={mode === "create" ? "New annotation" : "Edit annotation"}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold">{mode === "create" ? `New ${TYPE_LABEL[type].toLowerCase()}` : TYPE_LABEL[type]}</span>
        {annotation ? <SourceBadge source={annotation.source} /> : <SourceBadge source="human" />}
        {annotation?.confidence != null ? <ConfidenceBadge value={annotation.confidence} /> : null}
        {annotation ? <span className="ml-auto font-mono text-[11px] text-ink-3">rev {annotation.revision}</span> : null}
      </div>

      {annotation?.source === "auto" && canEdit ? (
        <p className="rounded-md border border-ai-line bg-ai-bg px-2.5 py-2 text-xs text-ai">
          This is an AI prediction. Saving a change creates a human correction; the original prediction is kept in its history.
        </p>
      ) : null}

      <div className="flex flex-col gap-1">
        <label htmlFor={`${id}-label`} className="text-xs font-semibold">Label</label>
        <input
          id={`${id}-label`}
          className={inputClass}
          value={v.label}
          list={`${id}-labels`}
          required
          maxLength={200}
          autoFocus={mode === "create"}
          readOnly={readOnly}
          onChange={(e) => set({ label: e.target.value })}
          placeholder="e.g. reach, grasp, mug"
        />
        <datalist id={`${id}-labels`}>
          {labels.map((l) => <option key={l.label} value={l.label} />)}
        </datalist>
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor={`${id}-category`} className="text-xs font-semibold">Category</label>
        <select id={`${id}-category`} className={inputClass} value={v.category} disabled={readOnly} onChange={(e) => set({ category: e.target.value as AnnotationCategory })}>
          {CATEGORIES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
        </select>
      </div>

      <div className="grid grid-cols-2 gap-2">
        {(["frame_start", "frame_end"] as const).map((field) => (
          <div key={field} className="flex min-w-0 flex-col gap-1">
            <label htmlFor={`${id}-${field}`} className="text-xs font-semibold">{field === "frame_start" ? "Start frame" : "End frame"}</label>
            <div className="flex gap-1">
              <input
                id={`${id}-${field}`}
                type="number"
                min={0}
                max={last}
                className={`${inputClass} min-w-0 font-mono`}
                value={v[field]}
                readOnly={readOnly}
                onChange={(e) => set({ [field]: Math.max(0, Math.round(Number(e.target.value) || 0)) })}
              />
              {canEdit ? (
                <button
                  type="button"
                  title="Use the current frame"
                  aria-label={`Set ${field === "frame_start" ? "start" : "end"} to the current frame`}
                  onClick={() => set({ [field]: currentFrame() })}
                  className="grid size-[34px] flex-none place-items-center rounded-md border border-line hover:bg-hover"
                >
                  <Crosshair className="size-3.5" aria-hidden />
                </button>
              ) : null}
            </div>
          </div>
        ))}
      </div>
      {rangeError ? <p className="text-xs text-error">{rangeError}</p> : null}

      {type === "bbox" ? (
        <div className="flex flex-col gap-1">
          <span className="text-xs font-semibold">Box</span>
          {v.box ? (
            <span className="font-mono text-[11px] text-ink-2">
              x {fmt(v.box[0])} · y {fmt(v.box[1])} · w {fmt(v.box[2])} · h {fmt(v.box[3])}
            </span>
          ) : (
            <span className="text-xs text-warning">Drag on the picture to draw the box.</span>
          )}
          {canEdit && onRedraw && v.box ? (
            <button type="button" onClick={onRedraw} className="self-start text-xs font-medium underline">Redraw box</button>
          ) : null}
        </div>
      ) : null}

      {type === "keypoint" ? (
        <div className="flex flex-col gap-1.5">
          <span className="text-xs font-semibold">Points</span>
          {!v.points?.length ? <span className="text-xs text-warning">Click on the picture to place points.</span> : null}
          {v.points?.map((p, i) => (
            <div key={i} className="flex items-center gap-1.5">
              <input
                aria-label={`Point ${i + 1} name`}
                className={`${inputClass} h-[30px] min-w-0 flex-1`}
                value={p.name}
                readOnly={readOnly}
                maxLength={64}
                onChange={(e) => set({ points: v.points!.map((q, j) => (j === i ? { ...q, name: e.target.value } : q)) })}
              />
              <label className="flex items-center gap-1 text-[11px] text-ink-2">
                <input
                  type="checkbox"
                  checked={p.visible}
                  disabled={readOnly}
                  onChange={(e) => set({ points: v.points!.map((q, j) => (j === i ? { ...q, visible: e.target.checked } : q)) })}
                />
                visible
              </label>
              {canEdit ? (
                <button
                  type="button"
                  aria-label={`Remove point ${p.name}`}
                  onClick={() => set({ points: v.points!.filter((_, j) => j !== i) })}
                  className="grid size-[30px] place-items-center rounded-md border border-line hover:bg-hover"
                >
                  <Trash2 className="size-3.5" aria-hidden />
                </button>
              ) : null}
            </div>
          ))}
          {canEdit && onRedraw && v.points?.length ? (
            <button type="button" onClick={onRedraw} className="self-start text-xs font-medium underline">Place more points</button>
          ) : null}
        </div>
      ) : null}

      <label className="flex items-center gap-2 text-xs">
        <input type="checkbox" checked={v.needs_review} disabled={readOnly} onChange={(e) => set({ needs_review: e.target.checked })} />
        Needs review
      </label>

      {annotation ? (
        <p className="text-[11px] text-ink-3">
          {annotation.author ? `By ${annotation.author.name}` : "Created by a model"} · {new Date(annotation.created_at).toLocaleString()}
          {annotation.updated_at ? ` · edited ${new Date(annotation.updated_at).toLocaleString()}` : ""}
        </p>
      ) : null}

      {error ? <p role="alert" className="rounded-md border border-error-line bg-error-bg px-2.5 py-2 text-xs text-error">{error}</p> : null}

      {canEdit ? (
        <div className="flex gap-2">
          <button
            type="submit"
            disabled={busy || !!rangeError || geometryMissing || !v.label.trim()}
            className="h-8 rounded-md bg-ink px-3 text-xs font-semibold text-canvas disabled:opacity-40"
          >
            {busy ? "Saving…" : mode === "create" ? "Save annotation" : "Save changes"}
          </button>
          <button type="button" onClick={onCancel} className="h-8 rounded-md border border-line px-3 text-xs font-semibold hover:bg-hover">
            {mode === "create" ? "Discard" : "Close"}
          </button>
        </div>
      ) : null}
    </form>
  );
}
