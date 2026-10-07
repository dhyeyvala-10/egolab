"use client";

import { DataTable, EmptyState, useLocalTable, type Column } from "@/components/ui";
import type { DeviceSummary } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";

const COLUMNS: Column<DeviceSummary>[] = [
  { key: "name", header: "Device", sortable: true, cell: (d) => <span className="font-medium">{d.name}</span> },
  { key: "kind", header: "Kind", sortable: true },
  { key: "serial", header: "Serial", cell: (d) => (d.serial ? <span className="font-mono text-xs">{d.serial}</span> : null) },
  { key: "session_count", header: "Sessions", sortable: true, align: "right" },
  { key: "video_count", header: "Videos", sortable: true, align: "right" },
  { key: "created_at", header: "Added", sortable: true, className: "whitespace-nowrap", cell: (d) => formatDateTime(d.created_at) },
];

/** Devices are few (a fleet of cameras), so this list is sorted and filtered in the browser. */
export function DeviceTable({ devices }: { devices: DeviceSummary[] }) {
  const table = useLocalTable(devices, COLUMNS, 50);
  return (
    <DataTable
      {...table}
      columns={COLUMNS}
      rowKey={(d) => d.id}
      filterPlaceholder="Filter devices"
      caption="Devices"
      empty={<EmptyState size="compact" title={table.filter ? "No devices match" : "No devices yet"} description={table.filter ? undefined : "Add the cameras and glasses you record with."} />}
    />
  );
}
