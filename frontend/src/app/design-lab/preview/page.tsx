// One concept, one screen, full page. The lab embeds this in frames of real widths, so every media query responds
// exactly as it would on a phone or a desktop.
import { notFound } from "next/navigation";
import { ConceptView } from "@/components/design-lab/ConceptView";
import { isConcept, isScreen } from "@/components/design-lab/concepts";

export default async function DesignLabPreview({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  if (process.env.NODE_ENV === "production") notFound();
  const sp = await searchParams;
  const concept = isConcept(sp.c) ? sp.c : "calm";
  const screen = isScreen(sp.s) ? sp.s : "home";
  return <ConceptView concept={concept} initialScreen={screen} />;
}
