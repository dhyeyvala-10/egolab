import { api } from "@/lib/api/client";

/** Sessions and datasets a run or schedule can take, for the input pickers (server side). */
export async function inputOptions(token: string) {
  const [sessions, datasets] = await Promise.all([api.sessions(token, { limit: 200 }), api.datasets(token)]);
  return {
    sessions: sessions.ok
      ? sessions.data.items.map((s) => ({ id: s.id, name: s.task ? `${s.name} · ${s.task}` : s.name, hint: `${s.stats.ready_count} ready` }))
      : [],
    datasets: datasets.ok ? datasets.data.items.map((d) => ({ id: d.id, name: d.name, hint: `${d.session_count} sessions` })) : [],
  };
}
