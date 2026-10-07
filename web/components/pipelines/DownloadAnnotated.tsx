"use client";

import { useState } from "react";
import { browserApi } from "@/lib/api/browser";
import { cn } from "@/lib/cn";

interface Download {
  url: string;
  filename: string;
}

/** Save an annotated video: asks the API for a short-lived link, then downloads it under its name. */
export function DownloadAnnotated({ id, label = "Download", small = false }: { id: string; label?: string; small?: boolean }) {
  const [error, setError] = useState<string | null>(null);
  const go = async () => {
    setError(null);
    const res = await browserApi<Download>(`/annotated-videos/${id}/download`);
    if (!res.ok) {
      setError(res.message);
      return;
    }
    const a = document.createElement("a");
    a.href = res.data.url;
    a.download = res.data.filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
  };
  return (
    <span className="inline-flex items-center gap-1.5">
      <button type="button" onClick={go} data-annotated={id}
              className={cn(small ? "underline" : "inline-flex h-[28px] items-center rounded-md bg-accent px-2.5 font-semibold text-on-accent hover:opacity-90")}>
        {small ? label : `↓ ${label}`}
      </button>
      {error ? <span role="alert" className="text-error">{error}</span> : null}
    </span>
  );
}
