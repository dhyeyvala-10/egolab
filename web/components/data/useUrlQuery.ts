"use client";

import { usePathname, useRouter } from "next/navigation";
import { useCallback, useTransition } from "react";

export type Query = Record<string, string | undefined>;

/**
 * Tables driven by the URL: the server page reads the query, fetches one page from the API, and this hook
 * pushes a new query when the user sorts, filters, or pages — so nothing loads the full table.
 */
export function useUrlQuery(current: Query) {
  const router = useRouter();
  const pathname = usePathname();
  const [pending, startTransition] = useTransition();

  const set = useCallback(
    (changes: Query, { resetPage = true }: { resetPage?: boolean } = {}) => {
      const next = new URLSearchParams();
      const merged: Query = { ...current, ...changes, ...(resetPage && !("offset" in changes) ? { offset: undefined } : {}) };
      for (const [key, value] of Object.entries(merged)) if (value) next.set(key, value);
      const search = next.toString();
      startTransition(() => router.push(search ? `${pathname}?${search}` : pathname, { scroll: false }));
    },
    [current, pathname, router],
  );

  return { set, pending };
}
