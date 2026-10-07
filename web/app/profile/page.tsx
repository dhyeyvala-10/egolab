import { ArrowRight, Check, LogOut } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { ApiUnavailable } from "@/components/auth/ApiUnavailable";
import { WaitingForAccess } from "@/components/auth/WaitingForAccess";
import { ThemeToggle } from "@/components/theme/ThemeToggle";
import { api, apiUrl, type ApiResult } from "@/lib/api/client";
import type { AssignmentRead, Page, Role } from "@/lib/api/types";
import { logout } from "@/lib/auth/actions";
import { getSession } from "@/lib/auth/session";
import { cn } from "@/lib/cn";
import { initials } from "@/lib/format";

export const metadata: Metadata = { title: "Your profile" };

/** Roles with access (someone still waiting for it sees the waiting screen instead of this page). */
type ActiveRole = Exclude<Role, "pending">;

const ROLE_LABEL: Record<ActiveRole, string> = { admin: "Admin", annotator: "Annotator", reviewer: "Reviewer", viewer: "Viewer" };

const ROLE_BLURB: Record<ActiveRole, string> = {
  admin: "Runs the workspace: people, pipelines, and every module.",
  annotator: "Labels video in the inspector and works through the queue.",
  reviewer: "Checks what the models and annotators found, and hands out work.",
  viewer: "Browses videos, datasets, and results.",
};

interface DeskCard {
  label: string;
  value: number | null;
  hint: string;
  href: string;
}

const numberFormat = new Intl.NumberFormat("en-US");

function total(res: ApiResult<Page<unknown>>): number | null {
  return res.ok ? res.data.total : null;
}

function sum(...values: (number | null)[]): number | null {
  return values.includes(null) ? null : values.reduce<number>((a, b) => a + (b ?? 0), 0);
}

function resumeHref(a: AssignmentRead): string {
  if (a.video) return `/annotation/inspector/${a.video.id}`;
  return a.session ? `/annotation/inspector?session_id=${a.session.id}` : "/annotation/queue";
}

/** Step 2 of landing → profile → dashboard: who you are, what's on your desk, then on to the dashboard. */
export default async function ProfilePage() {
  const session = await getSession();
  if (session.status === "anonymous") redirect(`/auth/signed-out?next=${encodeURIComponent("/profile")}`);
  if (session.status === "unavailable") return <ApiUnavailable message={session.message} />;
  if (session.user.role === "pending") return <WaitingForAccess user={session.user} />;
  const { token } = session;
  const user = { ...session.user, role: session.user.role as ActiveRole };

  const mine = { mine: true, limit: 1 };
  const [overview, inProgress, todo, done, flagged] = await Promise.all([
    api.overview(token),
    api.assignments(token, { ...mine, status: "in_progress" }),
    api.assignments(token, { ...mine, status: "todo" }),
    api.assignments(token, { ...mine, status: "done" }),
    api.movementEvents(token, { limit: 1, status: "needs_review" }),
  ]);
  const counts = overview.ok ? overview.data.counts : null;
  const open = sum(total(inProgress), total(todo));
  const resume = (inProgress.ok && inProgress.data.items[0]) || (todo.ok && todo.data.items[0]) || null;

  const cards: Record<"open" | "done" | "flagged" | "jobs" | "videos" | "datasets", DeskCard> = {
    open: { label: "Assigned to you", value: open, hint: "sessions and videos still open", href: "/annotation/queue" },
    done: { label: "Finished", value: total(done), hint: "assignments you completed", href: "/annotation/queue" },
    flagged: { label: "Flagged for review", value: total(flagged), hint: "movement events waiting on a person", href: "/cv/movements" },
    jobs: { label: "Active jobs", value: counts?.jobs_active ?? null, hint: "queued, running, or retrying", href: "/pipelines/runs" },
    videos: { label: "Videos", value: counts?.videos ?? null, hint: "in the library", href: "/data/videos" },
    datasets: { label: "Datasets", value: counts?.datasets ?? null, hint: "you can browse", href: "/datasets/versions" },
  };
  const desks: Record<ActiveRole, [DeskCard, DeskCard]> = {
    admin: [cards.jobs, cards.flagged],
    annotator: [cards.open, cards.done],
    reviewer: [cards.flagged, cards.open],
    viewer: [cards.videos, cards.datasets],
  };
  const desk = desks[user.role];

  const name = user.name || user.email;

  return (
    <div className="min-h-full bg-ground text-[15px] leading-relaxed">
      <div className="mx-auto flex max-w-[1280px] flex-col gap-10 px-4 py-6 md:px-8">
        <header className="flex items-center justify-between gap-4">
          <Link href="/" className="flex items-center gap-2">
            <span className="grid size-7 place-items-center rounded-lg bg-ink text-xs font-extrabold text-ground">EL</span>
            <span className="font-bold tracking-tight">Ego Labs</span>
          </Link>
          <ol aria-label="Getting started" className="hidden items-center gap-2 font-mono text-xs sm:flex">
            <li className="flex items-center gap-1.5 rounded-full bg-hover px-3 py-1.5 text-ink-2">
              <Check className="size-3" aria-hidden />
              Welcome
            </li>
            <li aria-current="step" className="rounded-full bg-accent px-3 py-1.5 font-semibold text-on-accent">
              Profile
            </li>
            <li className="rounded-full border border-line px-3 py-1.5 text-ink-3">Dashboard</li>
          </ol>
          <ThemeToggle className="size-10" />
        </header>

        <div className="grid grid-cols-1 gap-5 lg:grid-cols-[400px_minmax(0,1fr)]">
          <section aria-labelledby="profile-name" className="flex flex-col gap-6 rounded-[32px] bg-ink p-8 text-ground">
            <div aria-hidden className="grid size-28 place-items-center rounded-[32px] bg-accent text-4xl font-extrabold tracking-tight text-on-accent">
              {initials(name)}
            </div>
            <div className="flex flex-col gap-1">
              <div className="font-mono text-xs text-ground/70">Welcome back</div>
              <h1 id="profile-name" className="break-words text-4xl font-extrabold leading-[1.05] tracking-[-0.03em]">
                {name}
              </h1>
              {user.name ? <div className="break-all text-ground/75">{user.email}</div> : null}
            </div>
            <div className="flex flex-col gap-2 rounded-2xl border border-ground/20 p-4">
              <div className="font-mono text-xs text-ground/70">Working as</div>
              <div className="text-xl font-bold">{ROLE_LABEL[user.role]}</div>
              <p className="text-sm text-ground/75">{ROLE_BLURB[user.role]}</p>
            </div>
            <div className="mt-auto flex flex-wrap items-center justify-between gap-3 pt-2">
              <form action={logout}>
                <button type="submit" className="flex h-11 items-center gap-2 rounded-full border border-ground/30 px-4 text-sm font-semibold hover:bg-ground/10">
                  <LogOut className="size-4" aria-hidden />
                  Sign out
                </button>
              </form>
              <span className="truncate font-mono text-xs text-ground/60" title={apiUrl()}>
                API {apiUrl()}
              </span>
            </div>
          </section>

          <section aria-label="Your desk" className="grid grid-cols-1 gap-5 sm:grid-cols-2">
            <div className="flex flex-col justify-between gap-5 rounded-[32px] border border-line bg-canvas p-7 sm:col-span-2 md:flex-row md:items-center">
              <div className="flex min-w-0 flex-col gap-1.5">
                <div className="font-mono text-xs text-accent">Pick up where you left off</div>
                {resume ? (
                  <>
                    <div className="truncate text-2xl font-extrabold tracking-tight">{resume.video?.name ?? resume.session?.name}</div>
                    <div className="text-ink-2">
                      {resume.progress.annotated} of {resume.progress.videos} video{resume.progress.videos === 1 ? "" : "s"} annotated
                      {resume.note ? ` · ${resume.note}` : ""}
                    </div>
                  </>
                ) : (
                  <>
                    <div className="text-2xl font-extrabold tracking-tight">Nothing in progress</div>
                    <div className="text-ink-2">
                      {inProgress.ok ? "No open assignments. Browse the library or the queue." : "Assignments couldn't be loaded."}
                    </div>
                  </>
                )}
              </div>
              <Link
                href={resume ? resumeHref(resume) : "/data/videos"}
                className="flex h-12 flex-none items-center gap-2 self-start rounded-full border border-line px-5 font-bold hover:bg-hover md:self-auto"
              >
                {resume ? "Resume" : "Open the library"}
              </Link>
            </div>

            {desk.map((card, i) => (
              <Link
                key={card.label}
                href={card.href}
                className={cn(
                  "flex min-h-[200px] flex-col justify-between gap-6 rounded-[28px] p-7 hover:opacity-90",
                  i === 0 ? "bg-accent-soft" : "bg-sage-soft",
                )}
              >
                <span className={cn("font-mono text-xs", i === 0 ? "text-accent" : "text-sage")}>{card.label}</span>
                <span className="flex flex-col gap-1">
                  <span className={cn("text-6xl font-extrabold leading-none tracking-[-0.04em] tabular-nums", card.value === null && "text-ink-3")}>
                    {card.value === null ? "—" : numberFormat.format(card.value)}
                  </span>
                  <span className="text-ink-2">{card.hint}</span>
                </span>
              </Link>
            ))}

            <Link
              href="/dashboard"
              className="flex h-[88px] items-center justify-between rounded-full bg-accent pl-9 pr-4 text-on-accent hover:opacity-95 sm:col-span-2"
            >
              <span className="text-xl font-extrabold tracking-tight md:text-2xl">Go to my dashboard</span>
              <span aria-hidden className="grid size-[60px] place-items-center rounded-full bg-on-accent text-accent">
                <ArrowRight className="size-6" />
              </span>
            </Link>
          </section>
        </div>
      </div>
    </div>
  );
}
