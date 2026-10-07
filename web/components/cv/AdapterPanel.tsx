import { Panel } from "@/components/ui/Panel";
import { KeyValues } from "@/components/ui/KeyValues";
import type { AdapterInfo } from "@/lib/api/types";

/** Which model new runs of a kind use. Changed by configuration (the two settings in `info.env`), not here. */
export function AdapterPanel({ info, title = "Model" }: { info: AdapterInfo; title?: string }) {
  const config = Object.keys(info.config).length ? JSON.stringify(info.config) : "defaults";
  const [adapterEnv, configEnv] = info.env;
  return (
    <Panel title={title} hint={`Set by ${adapterEnv} and ${configEnv}`}>
      <KeyValues
        rows={[
          ["Adapter", <span key="a" className="font-mono text-xs">{info.name}</span>],
          ["Class", <span key="c" className="font-mono text-xs break-all">{info.target}</span>],
          ["Config", <span key="g" className="font-mono text-xs break-all">{config}</span>],
          ["Model version", info.model_version ? <span key="v" className="font-mono text-xs">{info.model_version.name} {info.model_version.version}</span> : <span key="v" className="text-ink-3">Registered on the first run with this setup</span>],
          ["Status", info.runnable ? "Ready" : <span key="s" className="text-error">{info.error}</span>],
          ["Available", <span key="r" className="text-xs text-ink-2">{info.registered.map((n) => (info.stubs.includes(n) ? `${n} (stub)` : n)).join(", ")}</span>],
        ]}
      />
    </Panel>
  );
}
