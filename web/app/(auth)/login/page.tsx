import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { GoogleSignIn } from "@/components/auth/GoogleSignIn";
import { api } from "@/lib/api/client";
import { AFTER_SIGN_IN, SIGN_IN_ERRORS, signInError } from "@/lib/auth/google";
import { getSession, safeNext } from "@/lib/auth/session";

export const metadata: Metadata = { title: "Sign in" };

/** The one login page: continue with Google. Signing in lands on the dashboard (or the page asked for). */
export default async function LoginPage({ searchParams }: PageProps<"/login">) {
  const params = await searchParams;
  const next = safeNext(params.next);
  if ((await getSession()).status === "authenticated") redirect(next === "/" ? AFTER_SIGN_IN : next);

  const config = await api.googleConfig();
  const enabled = config.ok && config.data.enabled;
  const error = signInError(params.error)
    ?? (!config.ok ? SIGN_IN_ERRORS.unavailable : !enabled ? SIGN_IN_ERRORS.not_configured : undefined);
  return (
    <GoogleSignIn
      enabled={enabled}
      next={next === "/" ? undefined : next}
      error={error}
      notice={params.expired ? "Your session ended. Sign in again to continue." : undefined}
    />
  );
}
