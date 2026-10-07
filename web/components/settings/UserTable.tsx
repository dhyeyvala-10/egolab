"use client";

import { useState, useTransition } from "react";
import { DataTable, EmptyState, StatusBadge, type Column } from "@/components/ui";
import type { GrantableRole, UserRead } from "@/lib/api/types";
import { setActive, setRole } from "@/lib/actions/admin";
import { formatDateTime } from "@/lib/format";
import { ROLE_CHOICES } from "@/lib/roles";
import { useNow } from "@/lib/useNow";
import { inputClass } from "@/components/data/Field";

const ONLINE_MS = 5 * 60 * 1000;

/** "Online now" when the account made a request in the last few minutes. */
export function isOnline(user: UserRead, now: number): boolean {
  return !!user.last_seen_at && now - new Date(user.last_seen_at).getTime() < ONLINE_MS;
}

function RoleCell({ user, me }: { user: UserRead; me?: string }) {
  const [pending, start] = useTransition();
  const [error, setError] = useState<string>();
  if (user.is_owner) return <StatusBadge status="ready" label={user.id === me ? "Admin (you)" : "Admin"} />;
  return (
    <div className="flex flex-col gap-1">
      <select
        aria-label={`Access for ${user.email}`}
        className={`${inputClass} h-8 py-0`}
        value={user.role}
        disabled={pending}
        onChange={(e) => {
          const role = e.target.value as GrantableRole;
          start(async () => setError((await setRole(user.id, role)).error));
        }}
      >
        {ROLE_CHOICES.map((r) => (
          <option key={r.value} value={r.value}>{r.label}</option>
        ))}
      </select>
      {error ? <span className="text-xs text-error">{error}</span> : null}
    </div>
  );
}

function BlockCell({ user }: { user: UserRead }) {
  const [pending, start] = useTransition();
  const [error, setError] = useState<string>();
  if (user.is_owner) return null;
  return (
    <div className="flex flex-col items-end gap-1">
      <button
        type="button"
        disabled={pending}
        onClick={() => start(async () => setError((await setActive(user.id, !user.is_active)).error))}
        className="h-8 rounded-md border border-line px-3 text-xs font-semibold hover:bg-hover disabled:opacity-50"
      >
        {user.is_active ? "Block" : "Unblock"}
      </button>
      {error ? <span className="text-xs text-error">{error}</span> : null}
    </div>
  );
}

export function UserTable({ users, me }: { users: UserRead[]; me?: string }) {
  const now = useNow(30_000);
  const columns: Column<UserRead>[] = [
    {
      key: "email",
      header: "Person",
      cell: (u) => (
        <div className="flex min-w-0 flex-col">
          <span className="truncate font-medium">{u.name || u.email}</span>
          {u.name ? <span className="truncate text-xs text-ink-3">{u.email}</span> : null}
        </div>
      ),
    },
    { key: "role", header: "Access", cell: (u) => <RoleCell user={u} me={me} /> },
    {
      key: "is_active",
      header: "Status",
      cell: (u) =>
        !u.is_active ? (
          <StatusBadge status="failed" label="Blocked" />
        ) : u.role === "pending" ? (
          <StatusBadge status="pending" label="Waiting for access" />
        ) : isOnline(u, now) ? (
          <StatusBadge status="running" label="Online now" />
        ) : (
          <StatusBadge status="aborted" label="Offline" />
        ),
    },
    { key: "last_sign_in_at", header: "Last sign-in", className: "whitespace-nowrap", cell: (u) => (u.last_sign_in_at ? formatDateTime(u.last_sign_in_at) : "—") },
    { key: "created_at", header: "Joined", className: "whitespace-nowrap", cell: (u) => formatDateTime(u.created_at) },
    { key: "id", header: "", align: "right", cell: (u) => <BlockCell user={u} /> },
  ];
  return (
    <DataTable
      columns={columns}
      rows={users}
      rowKey={(u) => u.id}
      caption="People"
      empty={<EmptyState size="compact" title="Nobody has signed in yet" />}
    />
  );
}
