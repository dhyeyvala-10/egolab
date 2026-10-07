import type { ReactNode } from "react";

/** Compact label/value list. `null`/`undefined` values render as an em dash. */
export function KeyValues({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[minmax(110px,auto)_minmax(0,1fr)] text-[13px]">
      {rows.map(([label, value]) => (
        <div key={label} className="contents">
          <dt className="border-b border-line py-1.5 pr-3 text-ink-2 last-of-type:border-b-0">{label}</dt>
          <dd className="min-w-0 border-b border-line py-1.5 break-words last-of-type:border-b-0">
            {value === null || value === undefined || value === "" ? <span className="text-ink-3">—</span> : value}
          </dd>
        </div>
      ))}
    </dl>
  );
}
