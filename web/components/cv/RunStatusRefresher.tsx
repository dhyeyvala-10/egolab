"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

/** Re-render the server page every few seconds while a run is waiting, queued, or running. */
export function RunStatusRefresher({ status }: { status: string }) {
  const router = useRouter();
  useEffect(() => {
    if (status !== "queued" && status !== "running" && status !== "waiting") return;
    const t = setInterval(() => router.refresh(), 3000);
    return () => clearInterval(t);
  }, [status, router]);
  return null;
}
