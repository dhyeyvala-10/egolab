import { Unplug } from "lucide-react";
import { EmptyState } from "@/components/ui";

/** Shown instead of the app shell when the session can't be checked because the API is down. */
export function ApiUnavailable({ message }: { message: string }) {
  return (
    <div className="grid min-h-full place-items-center px-4 py-10">
      <div className="w-full max-w-[520px] rounded-lg border border-warning-line bg-warning-bg">
        <EmptyState
          icon={<Unplug className="size-5 text-warning" aria-hidden />}
          title="The Ego Labs API is unavailable"
          description={
            <>
              <span className="block">{message}</span>
              <span className="mt-2 block">
                Start the stack with <code className="rounded border border-line bg-canvas px-1 font-mono text-xs">docker compose up</code>{" "}
                or set <code className="rounded border border-line bg-canvas px-1 font-mono text-xs">API_URL</code>, then reload.
              </span>
            </>
          }
        />
      </div>
    </div>
  );
}
