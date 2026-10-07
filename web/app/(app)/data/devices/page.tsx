import type { Metadata } from "next";
import { DeviceForm } from "@/components/data/DeviceForm";
import { DeviceTable } from "@/components/data/DeviceTable";
import { PageHeader } from "@/components/ui";
import { ErrorPanel } from "@/components/ui/ErrorPanel";
import { Panel } from "@/components/ui/Panel";
import { api } from "@/lib/api/client";
import { requireSession } from "@/lib/auth/session";

export const metadata: Metadata = { title: "Devices" };

export default async function DevicesPage() {
  const session = await requireSession("/data/devices");
  if (!session) return null;
  const res = await api.devices(session.token, { limit: 200 });
  return (
    <div className="flex max-w-[1760px] flex-col gap-5">
      <PageHeader eyebrow="Data" title="Devices" description="Capture devices, and how many sessions and videos were recorded on each." />
      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        {res.ok ? <DeviceTable devices={res.data.items} /> : <ErrorPanel title="Devices couldn't be loaded" message={res.message} />}
        <Panel title="Add a device" bodyClassName="py-3">
          <DeviceForm />
        </Panel>
      </div>
    </div>
  );
}
