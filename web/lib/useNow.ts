"use client";

import { useEffect, useState } from "react";

/** The current time, ticking every `everyMs` (read once per render, so rendering stays pure). */
export function useNow(everyMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), everyMs);
    return () => window.clearInterval(id);
  }, [everyMs]);
  return now;
}
