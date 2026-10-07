import Link from "next/link";

export default function NotFound() {
  return (
    <div className="grid min-h-full place-items-center px-4">
      <div className="flex flex-col items-center gap-2 text-center">
        <div className="font-mono text-xs text-ink-3">404</div>
        <h1 className="text-lg font-semibold">This page doesn&apos;t exist</h1>
        <Link href="/dashboard" className="mt-2 inline-flex h-[30px] items-center rounded-md border border-line-strong px-3 font-medium hover:bg-hover">
          Go to Overview
        </Link>
      </div>
    </div>
  );
}
