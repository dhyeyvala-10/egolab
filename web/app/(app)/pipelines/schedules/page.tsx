import type { Metadata } from "next";
import { Schedules } from "@/components/pipelines/Schedules";
import { PageHeader } from "@/components/ui";
import { ErrorPanel } from "@/components/ui/ErrorPanel";
import { api } from "@/lib/api/client";
import { requireSession } from "@/lib/auth/session";
import { inputOptions } from "@/lib/pipelineInputs";

export const metadata: Metadata = { title: "Schedules" };

export default async function SchedulesPage() {
  const session = await requireSession("/pipelines/schedules");
  if (!session) return null;
  const [schedules, pipelines, options] = await Promise.all([
    api.pipelineSchedules(session.token),
    api.pipelines(session.token, { templates: false, limit: 200 }),
    inputOptions(session.token),
  ]);
  return (
    <div className="flex max-w-[1760px] flex-col gap-5">
      <PageHeader
        eyebrow="Pipelines"
        title="Schedules"
        description="Run a pipeline on a cron schedule, in your time zone: e.g. every night on the sessions uploaded that day."
      />
      {schedules.ok ? (
        <Schedules schedules={schedules.data} pipelines={pipelines.ok ? pipelines.data.items : []} sessions={options.sessions}
                   datasets={options.datasets} canEdit={session.user.role !== "viewer"} />
      ) : <ErrorPanel title="Schedules couldn't be loaded" message={schedules.message} />}
    </div>
  );
}
