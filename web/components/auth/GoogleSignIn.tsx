/** Google's "G", in its own colours (Google's sign-in branding asks for the mark unchanged). */
function GoogleMark() {
  return (
    <svg viewBox="0 0 48 48" className="size-5 shrink-0" aria-hidden>
      <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
      <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
      <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
    </svg>
  );
}

/** The login page's one action: sign in (or make an account) with Google. */
export function GoogleSignIn({ next, error, notice, enabled }: {
  next?: string;
  error?: string;
  notice?: string;
  enabled: boolean;
}) {
  const href = next ? `/auth/google?next=${encodeURIComponent(next)}` : "/auth/google";
  return (
    <div className="flex flex-col gap-5">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Sign in</h1>
        <p className="mt-1 text-ink-2">Use your Google account to open your Ego Labs dashboard.</p>
      </div>
      {error ? (
        <div role="alert" className="rounded-md border border-error-line bg-error-bg px-3 py-2 text-[12.5px] text-error">{error}</div>
      ) : notice ? (
        <div role="status" className="rounded-md border border-line bg-subtle px-3 py-2 text-[12.5px] text-ink-2">{notice}</div>
      ) : null}
      {enabled ? (
        <a
          href={href}
          className="flex h-12 items-center justify-center gap-3 rounded-full border border-line-strong bg-canvas px-5 font-semibold hover:bg-hover"
        >
          <GoogleMark />
          Continue with Google
        </a>
      ) : (
        <span
          aria-disabled="true"
          className="flex h-12 cursor-not-allowed items-center justify-center gap-3 rounded-full border border-line bg-subtle px-5 font-semibold text-ink-3"
        >
          <GoogleMark />
          Continue with Google
        </span>
      )}
      <p className="text-center text-xs text-ink-3">New here? Signing in with Google creates your account.</p>
    </div>
  );
}
