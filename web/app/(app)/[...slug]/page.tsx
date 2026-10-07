import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { NotYetBuilt } from "@/components/ui/NotYetBuilt";
import { NAV } from "@/lib/nav";

/** Every nav page that is not built yet is served by this route with the "Not yet built" state. */
const UNBUILT = NAV.flatMap((section) =>
  section.pages.filter((p) => !p.built).map((page) => ({ page, section: section.label })),
);

function lookup(slug: string[]) {
  const href = `/${slug.join("/")}`;
  return UNBUILT.find((u) => u.page.href === href);
}

export const dynamicParams = false;

export function generateStaticParams() {
  return UNBUILT.map((u) => ({ slug: u.page.href.slice(1).split("/") }));
}

export async function generateMetadata({ params }: PageProps<"/[...slug]">): Promise<Metadata> {
  const match = lookup((await params).slug);
  return { title: match?.page.label ?? "Not found" };
}

export default async function UnbuiltPage({ params }: PageProps<"/[...slug]">) {
  const match = lookup((await params).slug);
  if (!match) notFound();
  return <NotYetBuilt page={match.page} section={match.section} />;
}
