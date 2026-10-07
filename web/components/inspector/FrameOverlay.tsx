"use client";

import { useRef, useState, type PointerEvent } from "react";
import type { AnnotationRead } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { useFrame, type FrameStore } from "@/lib/inspector/frameStore";
import { normaliseBox, type Box, type DrawMode, type Point } from "@/lib/inspector/types";

const pct = (v: number) => `${v * 100}%`;

function tone(source: string) {
  return source === "auto" ? "border-ai text-ai" : "border-human text-human";
}

function BoxShape({ box, label, className, onClick }: { box: Box; label?: string; className: string; onClick?: () => void }) {
  const [x, y, w, h] = box;
  return (
    <div
      className={cn("absolute border-2", className, onClick && "pointer-events-auto cursor-pointer")}
      style={{ left: pct(x), top: pct(y), width: pct(w), height: pct(h) }}
      onClick={onClick}
    >
      {label ? (
        <span className="absolute -top-5 left-0 max-w-[16rem] truncate rounded-sm bg-canvas/90 px-1 text-[10.5px] font-semibold leading-4">{label}</span>
      ) : null}
    </div>
  );
}

function Points({ points, className, onClick }: { points: Point[]; className: string; onClick?: () => void }) {
  return (
    <>
      {points.map((p) => (
        <div
          key={p.name}
          title={p.name}
          onClick={onClick}
          className={cn("absolute size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 bg-canvas", className, !p.visible && "border-dashed opacity-60", onClick && "pointer-events-auto cursor-pointer")}
          style={{ left: pct(p.x), top: pct(p.y) }}
        >
          <span className="pointer-events-none absolute left-3 top-[-5px] whitespace-nowrap rounded-sm bg-canvas/90 px-1 text-[10px] leading-4">{p.name}</span>
        </div>
      ))}
    </>
  );
}

/**
 * Boxes and keypoints on the current frame, plus drawing. Coordinates are fractions of the frame, so the
 * overlay matches whatever size the player is drawn at.
 */
export function FrameOverlay({
  frameStore,
  annotations,
  selectedId,
  onSelect,
  draftBox,
  draftPoints,
  draw,
  onBoxDrawn,
  onPointAdded,
}: {
  frameStore: FrameStore;
  annotations: AnnotationRead[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  draftBox?: Box;
  draftPoints?: Point[];
  draw: DrawMode;
  onBoxDrawn: (box: Box) => void;
  onPointAdded: (point: { x: number; y: number }) => void;
}) {
  const frame = useFrame(frameStore);
  const surface = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<{ a: { x: number; y: number }; b: { x: number; y: number } } | null>(null);
  const onFrame = annotations.filter((a) => a.frame_start <= frame && a.frame_end >= frame && a.id !== selectedId);
  const selected = annotations.find((a) => a.id === selectedId && a.frame_start <= frame && a.frame_end >= frame);

  const at = (e: PointerEvent) => {
    const r = surface.current!.getBoundingClientRect();
    return { x: Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), y: Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)) };
  };

  const render = (a: AnnotationRead, isSelected: boolean) => {
    const cls = cn(tone(a.source), isSelected ? "border-[3px] border-ink" : "opacity-90");
    const click = draw ? undefined : () => onSelect(a.id);
    if (a.type === "bbox") return <BoxShape key={a.id} box={(a.data as { box: Box }).box} label={a.label} className={cls} onClick={click} />;
    if (a.type === "keypoint") return <Points key={a.id} points={(a.data as { points: Point[] }).points} className={cls} onClick={click} />;
    return null;
  };

  return (
    <div className="pointer-events-none absolute inset-0" data-testid="frame-overlay">
      {onFrame.map((a) => render(a, false))}
      {selected ? render(selected, true) : null}
      {draftBox ? <BoxShape box={draftBox} label="New" className="border-dashed border-ink" /> : null}
      {draftPoints?.length ? <Points points={draftPoints} className="border-ink" /> : null}
      {drag ? <BoxShape box={normaliseBox(drag.a, drag.b)} className="border-dashed border-ink" /> : null}
      {draw ? (
        <div
          ref={surface}
          data-testid="draw-surface"
          className="pointer-events-auto absolute inset-0 cursor-crosshair bg-ink/10"
          onPointerDown={(e) => {
            if (draw.kind !== "bbox") return;
            e.currentTarget.setPointerCapture(e.pointerId);
            const p = at(e);
            setDrag({ a: p, b: p });
          }}
          onPointerMove={(e) => drag && setDrag({ ...drag, b: at(e) })}
          onPointerUp={(e) => {
            if (draw.kind === "keypoint") {
              onPointAdded(at(e));
              return;
            }
            if (!drag) return;
            const box = normaliseBox(drag.a, at(e));
            setDrag(null);
            if (box[2] > 0.005 && box[3] > 0.005) onBoxDrawn(box);
          }}
        />
      ) : null}
    </div>
  );
}
