import { headers } from "next/headers";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";
import { ApiUnavailable } from "@/components/auth/ApiUnavailable";
import { WaitingForAccess } from "@/components/auth/WaitingForAccess";
import { AppShell } from "@/components/shell/AppShell";
import { apiUrl } from "@/lib/api/client";
import { PATH_HEADER } from "@/lib/auth/constants";
import { getSession } from "@/lib/auth/session";

export default async function AppLayout({ children }: { children: ReactNode }) {
  const session = await getSession();
  if (session.status === "anonymous") {
    const path = (await headers()).get(PATH_HEADER) ?? "/";
    redirect(`/auth/signed-out?next=${encodeURIComponent(path)}`);
  }
  if (session.status === "unavailable") return <ApiUnavailable message={session.message} />;
  // Signed in, but the admin hasn't given this account access yet: nothing of the app is shown.
  if (session.user.role === "pending") return <WaitingForAccess user={session.user} />;

  return (
    <AppShell user={session.user} apiUrl={apiUrl()}>
      {children}
    </AppShell>
  );
}
