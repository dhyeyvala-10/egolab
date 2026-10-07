import { ShieldAlert } from "lucide-react";
import { EmptyState } from "@/components/ui";

export function AdminOnly() {
  return (
    <div className="rounded-lg border border-line">
      <EmptyState
        icon={<ShieldAlert className="size-5 text-ink-2" aria-hidden />}
        title="Only the admin can open Settings"
        description="People, limits, requests, and activity are the admin's to manage."
      />
    </div>
  );
}
