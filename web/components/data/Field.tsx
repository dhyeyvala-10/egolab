import type { InputHTMLAttributes, ReactNode } from "react";

export const inputClass =
  "h-[32px] w-full rounded-md border border-line-strong bg-canvas px-2.5 placeholder:text-ink-3 focus:border-ink focus:outline-none";

export function Field({ id, label, hint, children, ...input }: { id: string; label: string; hint?: ReactNode; children?: ReactNode } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <label htmlFor={id} className="text-xs font-semibold">
        {label}
      </label>
      {children ?? <input id={id} name={id} className={inputClass} {...input} />}
      {hint ? <span className="text-xs text-ink-3">{hint}</span> : null}
    </div>
  );
}

export function FormMessage({ error, ok }: { error?: string; ok?: string }) {
  if (error) return <p role="alert" className="rounded-md border border-error-line bg-error-bg px-3 py-2 text-[12.5px] text-error">{error}</p>;
  if (ok) return <p role="status" className="text-xs text-success">{ok}</p>;
  return null;
}
