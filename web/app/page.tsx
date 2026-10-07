import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { HandFrame } from "@/components/landing/HandFrame";
import { ModuleGrid } from "@/components/landing/ModuleGrid";
import { PipelineStairs } from "@/components/landing/PipelineStairs";
import { ThemeToggle } from "@/components/theme/ThemeToggle";
import { getSession } from "@/lib/auth/session";
import { PIPELINE } from "@/lib/pipeline";

/** Public landing page. Signed-in visitors continue to their dashboard; everyone else signs in with Google first. */
export default async function LandingPage() {
  const session = await getSession();
  const signedIn = session.status === "authenticated";
  const enter = signedIn
    ? { href: "/dashboard", label: "Open your dashboard" }
    : { href: "/login", label: "Sign in" };

  return (
    <div className="min-h-full bg-ground text-[15px] leading-relaxed">
      <header className="sticky top-0 z-30 flex justify-center px-4 pt-4 md:pt-6">
        <nav
          aria-label="Site"
          className="flex w-full max-w-[760px] items-center gap-1 rounded-full border border-line bg-canvas/95 py-1.5 pl-4 pr-1.5 backdrop-blur"
        >
          <Link href="/" className="mr-auto flex items-center gap-2 md:mr-4">
            <span className="grid size-7 place-items-center rounded-lg bg-ink text-xs font-extrabold text-ground">EL</span>
            <span className="font-bold tracking-tight">Ego Labs</span>
          </Link>
          <a href="#pipeline" className="hidden rounded-full px-3.5 py-2 text-sm text-ink-2 hover:bg-hover hover:text-ink md:block">
            Pipeline
          </a>
          <a href="#modules" className="mr-auto hidden rounded-full px-3.5 py-2 text-sm text-ink-2 hover:bg-hover hover:text-ink md:block">
            Modules
          </a>
          <ThemeToggle className="size-10" />
          <Link
            href={enter.href}
            className="flex h-10 items-center gap-2 rounded-full bg-accent px-4 text-sm font-bold text-on-accent hover:opacity-90"
          >
            {signedIn ? "Enter workspace" : "Sign in"}
            <ArrowRight className="size-4" aria-hidden />
          </Link>
        </nav>
      </header>

      <main>
        <section className="mx-auto grid max-w-[1280px] grid-cols-1 items-center gap-12 px-4 py-16 md:px-8 md:py-24 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)] lg:gap-16">
          <div className="flex flex-col gap-7">
            <div className="flex items-center gap-2 self-start rounded-full border border-line px-3 py-1.5 font-mono text-xs text-ink-2">
              <span aria-hidden className="size-2 rounded-full bg-sage" />
              Egocentric data OS
            </div>
            <h1 className="text-5xl font-extrabold leading-[1.02] tracking-[-0.035em] md:text-7xl">
              See every hand,
              <br />
              every grasp,
              <br />
              <span className="text-accent">every frame.</span>
            </h1>
            <p className="max-w-[34em] text-lg text-ink-2">
              Ego Labs turns raw first-person video into tracked, annotated, versioned datasets, one level at a time.
            </p>
            <div className="flex flex-wrap items-center gap-3">
              <Link
                href={enter.href}
                className="flex h-13 items-center gap-2.5 rounded-full bg-ink px-6 font-bold text-ground hover:opacity-90"
              >
                {enter.label}
                <ArrowRight className="size-[18px]" aria-hidden />
              </Link>
              <a href="#pipeline" className="flex h-13 items-center rounded-full px-4 font-semibold text-ink-2 hover:text-ink">
                Walk the pipeline
              </a>
            </div>
          </div>
          <HandFrame />
        </section>

        <section id="pipeline" className="scroll-mt-24 border-y border-line bg-canvas">
          <div className="mx-auto flex max-w-[1280px] flex-col gap-12 px-4 py-20 md:px-8 md:py-24">
            <div className="flex flex-wrap items-end justify-between gap-6">
              <div className="flex flex-col gap-3">
                <div className="font-mono text-sm text-accent">The pipeline · {PIPELINE.length} levels</div>
                <h2 className="text-4xl font-extrabold leading-[1.05] tracking-[-0.03em] md:text-5xl">Climb it level by level.</h2>
              </div>
              <p className="max-w-[28em] text-ink-2">
                Every video climbs the same stairs, from raw footage at the bottom to evaluated, exportable data at the top.
                Pick a level to see what happens there.
              </p>
            </div>
            <PipelineStairs />
          </div>
        </section>

        <section id="modules" className="mx-auto flex max-w-[1280px] scroll-mt-24 flex-col gap-10 px-4 py-20 md:px-8 md:py-24">
          <div className="flex flex-col gap-3">
            <div className="font-mono text-sm text-accent">The modules</div>
            <h2 className="text-4xl font-extrabold leading-[1.05] tracking-[-0.03em] md:text-5xl">One workspace, every stage.</h2>
          </div>
          <ModuleGrid />
        </section>
      </main>

      <footer className="mx-auto max-w-[1280px] px-4 pb-16 md:px-8">
        <div className="flex flex-col items-start justify-between gap-6 rounded-[32px] bg-ink px-8 py-10 text-ground md:flex-row md:items-center md:px-14 md:py-12">
          <div className="flex flex-col gap-2">
            <div className="text-3xl font-extrabold leading-[1.05] tracking-[-0.03em] md:text-4xl">Your desk is waiting.</div>
            <div className="text-ground/75">
              {signedIn ? "Pick up where you left off." : "Sign in to pick up where you left off."}
            </div>
          </div>
          <Link
            href={enter.href}
            className="flex h-14 items-center gap-2.5 rounded-full bg-accent px-7 font-bold text-on-accent hover:opacity-90"
          >
            {signedIn ? "Enter workspace" : "Sign in"}
            <ArrowRight className="size-[18px]" aria-hidden />
          </Link>
        </div>
      </footer>
    </div>
  );
}
