// HAIP design lab: compare six UI directions on the same synthetic data. Development only.
import { notFound } from "next/navigation";
import { DesignLab } from "@/components/design-lab/DesignLab";
import { isConcept, isScreen } from "@/components/design-lab/concepts";

export default async function DesignLabPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  if (process.env.NODE_ENV === "production") notFound();
  const sp = await searchParams;
  return (
    <DesignLab
      initialConcept={isConcept(sp.c) ? sp.c : "atlas"}
      initialScreen={isScreen(sp.s) ? sp.s : "home"}
      initialMode={sp.m === "compare" ? "compare" : "single"}
    />
  );
}
