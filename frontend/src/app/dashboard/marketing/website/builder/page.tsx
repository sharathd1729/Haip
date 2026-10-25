"use client";
// Marketing › Website › Art director (W2): brief -> sitemap -> wireframe -> style -> a new-builder draft.
// Server gates: module "website" + website.approve (owner/manager); this page mirrors them for what it shows.
import Link from "next/link";
import { useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { Card, EmptyState, PageHeader } from "@/components/ui/kit";
import { Skeleton } from "@/components/ui/skeleton";
import { btn } from "@/components/marketing/studio/types";
import { ArtDirector } from "@/components/website/builder/ArtDirector";

export default function WebsiteBuilderPage() {
  const { data: session, status } = useSession();
  const role = String(session?.user?.role || "");
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const allowed = role === "owner" || role === "manager";
  return (
    <div className="h-full overflow-y-auto bg-[var(--haip-bg,var(--background))]">
      <div className="mx-auto max-w-[1280px] space-y-5 px-4 py-5 sm:px-6">
        <PageHeader title="Art director" subtitle="Plan your website step by step: brief, sitemap, wireframe, then pick a look."
          actions={<Link className={btn} href="/dashboard/marketing/website">Back to Website</Link>} />
        {!mounted || status === "loading" ? <Skeleton className="h-[50vh] w-full" />
          : !allowed ? <Card><EmptyState title="Only an owner or manager can plan the website" hint="Ask the workspace owner to run the art director." /></Card>
          : <ArtDirector />}
      </div>
    </div>
  );
}
