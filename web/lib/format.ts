const dateTime = new Intl.DateTimeFormat("en-GB", {
  year: "numeric",
  month: "short",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "UTC",
});

/** ISO timestamp → `23 Sept 2026, 10:55 UTC`. Fixed to UTC so server and client render identically. */
export function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : `${dateTime.format(d)} UTC`;
}

/** Seconds → `1:02:03`, `2:05`, or `8.4 s` for short clips. */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)} s`;
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

const UNITS = ["B", "KB", "MB", "GB", "TB"];

/** Bytes → `1.4 GB` (decimal units, like file managers). */
export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return "—";
  let value = bytes;
  let unit = 0;
  while (value >= 1000 && unit < UNITS.length - 1) {
    value /= 1000;
    unit += 1;
  }
  return `${value.toFixed(unit === 0 || value >= 100 ? 0 : 1)} ${UNITS[unit]}`;
}

/** 29.97002997 → `29.97`, 30 → `30`. */
export function formatFps(fps: number | null | undefined): string {
  if (fps === null || fps === undefined) return "—";
  return String(Math.round(fps * 100) / 100);
}

export function formatResolution(width: number | null | undefined, height: number | null | undefined): string {
  return width && height ? `${width}×${height}` : "—";
}

const numberFormat = new Intl.NumberFormat("en-US");

export function formatCount(n: number | null | undefined): string {
  return n === null || n === undefined ? "—" : numberFormat.format(n);
}

/** "Ada Lovelace" → "AL", "ada@example.com" → "AD". For avatar badges. */
export function initials(nameOrEmail: string): string {
  const words = nameOrEmail.split("@")[0].split(/[\s._-]+/).filter(Boolean);
  const letters = words.length > 1 ? words[0][0] + words[words.length - 1][0] : (words[0] ?? "?").slice(0, 2);
  return letters.toUpperCase();
}
