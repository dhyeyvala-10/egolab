import type { Metadata } from "next";
import { RunTable } from "@/components/cv/RunTable";
import { AutoAnnotateForm } from "@/components/review/AutoAnnotateForm";
import { PageHeader } from "@/components/ui";
import { ErrorPanel } from "@/components/ui/ErrorPanel";
import { Panel } from "@/components/ui/Panel";
import { api } from "@/lib/api/client";
import { requireSession } from "@/lib/auth/session";
import { formatDateTime } from "@/lib/format";

export const metadata: Metadata = { title: "Auto Annotation" };

export default async function AutoAnnotationPage() {
  const session = await requireSession("/annotation/auto");
  if (!session) return null;
  const [sessions, versions, runs] = await Promise.all([
    api.sessions(session.token, { limit: 200, sort: "created_at", order: "desc" }),
    api.modelVersions(session.token),
    api.cvRuns(session.token, { kind: "movement", limit: 20 }),
  ]);
  const canRun = session.user.role !== "viewer";
  return (
    <div className="flex max-w-[1200px] flex-col gap-5">
      <PageHeader
        eyebrow="Annotation"
        title="Auto Annotation"
        description="Run hand tracking, object detection, and movement classification on whole sessions, with the model version you choose. Each distinct setup is its own model version, so results stay comparable."
      />
      {canRun ? (
        <Panel title="Run">
          {sessions.ok && versions.ok ? <AutoAnnotateForm sessions={sessions.data.items} versions={versions.data} /> : <ErrorPanel title="Couldn't load sessions or models" message={!sessions.ok ? sessions.message : !versions.ok ? versions.message : ""} />}
        </Panel>
      ) : null}
      {runs.ok ? <RunTable page={runs.data} query={{}} base="/cv/movements/runs" kind="movement" controls={false} /> : null}
      <Panel title="Registered model versions" hint="Every adapter + config that has run">
        {versions.ok ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-xs" data-testid="model-versions">
              <thead className="text-left text-ink-3"><tr><th className="py-1.5 font-semibold">Kind</th><th className="font-semibold">Model</th><th className="font-semibold">Config</th><th className="text-right font-semibold">Runs</th><th className="text-right font-semibold">Last used</th></tr></thead>
              <tbody>
                {versions.data.map((v) => (
                  <tr key={v.id} className="border-t border-line">
                    <td className="py-1.5">{v.kind.replace(/_/g, " ")}</td>
                    <td><span className="font-medium">{v.name}</span> <span className="font-mono text-ink-3">{v.version}</span>{v.configured ? <span className="ml-1.5 rounded border border-line px-1 text-[10px] text-ink-2">configured</span> : null}</td>
                    <td className="max-w-72 truncate font-mono text-[11px] text-ink-2">{JSON.stringify(v.config)}</td>
                    <td className="text-right tabular-nums">{v.runs}</td>
                    <td className="text-right text-ink-2">{v.last_run_at ? formatDateTime(v.last_run_at) : "—"}</td>
                  </tr>
                ))}
                {!versions.data.length ? <tr><td colSpan={5} className="py-6 text-center text-ink-3">No model has run yet.</td></tr> : null}
              </tbody>
            </table>
          </div>
        ) : <ErrorPanel title="Model versions couldn't be loaded" message={versions.message} />}
      </Panel>
    </div>
  );
}
