"use client";

import { DataTable, EmptyState, type Column } from "@/components/ui";
import type { AdminActivity, SignInRead } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";

/** A short "Chrome on Windows" from a user agent string (the full string is in the tooltip). */
export function describeAgent(agent: string | null | undefined): string {
  if (!agent) return "Unknown";
  const browser = /Edg\//.test(agent) ? "Edge" : /Brave/.test(agent) ? "Brave" : /OPR\//.test(agent) ? "Opera"
    : /Firefox\//.test(agent) ? "Firefox" : /Chrome\//.test(agent) ? "Chrome" : /Safari\//.test(agent) ? "Safari" : null;
  const os = /Windows/.test(agent) ? "Windows" : /Android/.test(agent) ? "Android" : /iPhone|iPad/.test(agent) ? "iOS"
    : /Mac OS X|Macintosh/.test(agent) ? "macOS" : /Linux/.test(agent) ? "Linux" : null;
  if (browser && os) return `${browser} on ${os}`;
  return browser ?? os ?? agent.slice(0, 40);
}

export function SignInTable({ rows }: { rows: SignInRead[] }) {
  const columns: Column<SignInRead>[] = [
    { key: "created_at", header: "When", className: "whitespace-nowrap", cell: (s) => formatDateTime(s.created_at) },
    { key: "user_email", header: "Who", cell: (s) => <span className="font-medium">{s.user_name || s.user_email}</span> },
    { key: "user_agent", header: "Browser", cell: (s) => <span title={s.user_agent ?? undefined}>{describeAgent(s.user_agent)}</span> },
    { key: "ip", header: "Address", cell: (s) => <span className="font-mono text-xs">{s.ip ?? "—"}</span> },
  ];
  return <DataTable columns={columns} rows={rows} rowKey={(s) => s.id} caption="Sign-ins" empty={<EmptyState size="compact" title="No sign-ins yet" />} />;
}

export function ActionTable({ rows }: { rows: AdminActivity[] }) {
  const columns: Column<AdminActivity>[] = [
    { key: "created_at", header: "When", className: "whitespace-nowrap", cell: (e) => formatDateTime(e.created_at) },
    { key: "actor_email", header: "Who", cell: (e) => (e.actor_email ? <span className="font-medium">{e.actor_name || e.actor_email}</span> : <span className="text-ink-3">System</span>) },
    { key: "message", header: "What", cell: (e) => e.message },
  ];
  return <DataTable columns={columns} rows={rows} rowKey={(e) => String(e.id)} caption="Everything that happened" empty={<EmptyState size="compact" title="Nothing yet" />} />;
}
