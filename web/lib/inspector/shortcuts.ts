/** Inspector keyboard shortcuts (spec Phase 2). */
export type InspectorAction =
  | "togglePlay"
  | "prevFrame"
  | "nextFrame"
  | "prevEvent"
  | "nextEvent"
  | "create"
  | "review"
  | "delete"
  | "cancel"
  | "help";

export const SHORTCUTS: { keys: string[]; action: InspectorAction; label: string }[] = [
  { keys: ["Space"], action: "togglePlay", label: "Play / pause" },
  { keys: ["←", "→"], action: "prevFrame", label: "Previous / next frame" },
  { keys: ["Shift", "←", "→"], action: "prevEvent", label: "Previous / next event" },
  { keys: ["A"], action: "create", label: "Create annotation (press again to set the end)" },
  { keys: ["R"], action: "review", label: "Mark selected annotation for review" },
  { keys: ["Delete"], action: "delete", label: "Delete selected annotation (kept in history)" },
  { keys: ["Esc"], action: "cancel", label: "Cancel drawing / deselect" },
  { keys: ["?"], action: "help", label: "Show shortcuts" },
];

interface KeyLike {
  key: string;
  shiftKey: boolean;
  ctrlKey: boolean;
  metaKey: boolean;
  altKey: boolean;
  target: EventTarget | null;
}

export function isTyping(target: EventTarget | null): boolean {
  if (!target || typeof (target as HTMLElement).tagName !== "string") return false;
  const el = target as HTMLElement;
  const tag = el.tagName;
  if (tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable) return true;
  if (tag !== "INPUT") return false;
  const type = (el as HTMLInputElement).type;
  return !["checkbox", "radio", "button", "range", "submit", "reset"].includes(type);
}

/** Map a key press to an inspector action. Typing in a field, and browser/OS shortcuts, are left alone. */
export function actionFor(e: KeyLike): InspectorAction | null {
  if (e.ctrlKey || e.metaKey || e.altKey) return null;
  if (e.key === "Escape") return "cancel";
  if (isTyping(e.target)) return null;
  switch (e.key) {
    case " ":
      return "togglePlay";
    case "ArrowLeft":
      return e.shiftKey ? "prevEvent" : "prevFrame";
    case "ArrowRight":
      return e.shiftKey ? "nextEvent" : "nextFrame";
    case "a":
    case "A":
      return "create";
    case "r":
    case "R":
      return "review";
    case "Delete":
    case "Backspace":
      return "delete";
    case "?":
      return "help";
    default:
      return null;
  }
}
