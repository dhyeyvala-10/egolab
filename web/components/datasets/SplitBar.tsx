import type { VersionCounts } from "@/lib/api/types";
import { fullCounts, SPLITS } from "@/lib/datasets";

// Train / val / test are one ordered magnitude scale, so one hue in three steps (not status colours).
const TONES = { train: "bg-ink", val: "bg-ink-2", test: "bg-ink-3" } as const;

/** Samples per split as one bar (2px gaps), with counts and group counts labelled beside it. */
export function SplitBar({ counts: raw }: { counts: VersionCounts }) {
  const counts = fullCounts(raw);
  const total = Math.max(1, SPLITS.reduce((n, s) => n + (counts.splits[s] ?? 0), 0));
  return (
    <div className="flex flex-col gap-1.5" data-testid="split-bar">
      <div className="flex h-2 w-full gap-[2px] overflow-hidden rounded-full bg-hover" role="img"
           aria-label={SPLITS.map((s) => `${s} ${counts.splits[s]}`).join(", ")}>
        {SPLITS.filter((s) => counts.splits[s] > 0).map((s) => (
          <span key={s} className={`h-full first:rounded-l-full last:rounded-r-full ${TONES[s]}`} style={{ width: `${(counts.splits[s] / total) * 100}%` }} title={`${s}: ${counts.splits[s]}`} />
        ))}
      </div>
      <dl className="grid grid-cols-3 gap-2 text-xs">
        {SPLITS.map((s) => (
          <div key={s} className="flex flex-col">
            <dt className="flex items-center gap-1.5 capitalize text-ink-2"><span aria-hidden className={`size-2 rounded-full ${TONES[s]}`} />{s}</dt>
            <dd className="tabular-nums"><span className="font-semibold text-ink">{counts.splits[s]}</span> <span className="text-ink-3">· {counts.groups[s]} group{counts.groups[s] === 1 ? "" : "s"}</span></dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
