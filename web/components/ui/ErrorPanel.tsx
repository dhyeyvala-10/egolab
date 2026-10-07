import { EmptyState } from "./EmptyState";

/** An API call failed: say which and why, without placeholder data. */
export function ErrorPanel({ title, message }: { title: string; message: string }) {
  return (
    <section className="rounded-lg border border-error-line bg-error-bg">
      <EmptyState size="compact" title={title} description={message} />
    </section>
  );
}
