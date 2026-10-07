"use client";

import { DataTable, type Column } from "@/components/ui";
import { percent } from "@/lib/cv/skeleton";

export interface FingerStat {
  finger: string;
  samples: number;
  visibility: number | null;
  occluded_rate: number | null;
  mean_speed_px_s: number | null;
  p95_speed_px_s: number | null;
  peak_speed_px_s: number | null;
}

const fmt = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const speed = (v: number | null) => (v == null ? null : `${fmt.format(v)} px/s`);

const COLUMNS: Column<FingerStat>[] = [
  { key: "finger", header: "Finger", cell: (f) => <span className="capitalize">{f.finger}</span> },
  { key: "visibility", header: "Visible", align: "right", cell: (f) => percent(f.visibility, 1) },
  { key: "occluded_rate", header: "Estimated occluded", align: "right", cell: (f) => percent(f.occluded_rate, 1) },
  { key: "mean_speed_px_s", header: "Mean tip speed", align: "right", cell: (f) => speed(f.mean_speed_px_s) },
  { key: "p95_speed_px_s", header: "95th percentile", align: "right", cell: (f) => speed(f.p95_speed_px_s) },
  { key: "peak_speed_px_s", header: "Peak", align: "right", cell: (f) => speed(f.peak_speed_px_s) },
  { key: "samples", header: "Samples", align: "right", cell: (f) => fmt.format(f.samples) },
];

export function FingerStatsTable({ rows }: { rows: FingerStat[] }) {
  return <DataTable columns={COLUMNS} rows={rows} rowKey={(r) => r.finger} caption="Per-finger statistics" className="my-2" />;
}
