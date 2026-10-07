import { requireSession } from "./session";

/** For the admin's pages: the session when the signed-in account is the admin, else null (the page says so). */
export async function requireAdmin(next: string) {
  const session = await requireSession(next);
  if (!session) return { session: null, allowed: false } as const;
  return { session, allowed: session.user.role === "admin" } as const;
}
