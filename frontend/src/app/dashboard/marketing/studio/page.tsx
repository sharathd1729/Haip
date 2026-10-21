"use client";
// Marketing Studio (Phase 1): business profile, social audit, plan + calendar, AI-drafted content with approval,
// media library. Nothing is posted to Instagram from here yet. Server-side gates: module marketing_studio +
// marketing.* capabilities; this page only mirrors them.
import Link from "next/link";
import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import api from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, EmptyState, PageHeader, Tabs } from "@/components/ui/kit";
import { ContentTab } from "@/components/marketing/studio/ContentTab";
import { AgencyTab } from "@/components/marketing/studio/AgencyTab";
import { ApprovalsTab } from "@/components/marketing/studio/ApprovalsTab";
import { ResearchTab } from "@/components/marketing/studio/ResearchTab";
import { AuditTab, PlanTab } from "@/components/marketing/studio/InsightsTabs";
import { LibraryTab, ProfileTab } from "@/components/marketing/studio/ProfileLibraryTabs";
import { ReviewsTab } from "@/components/marketing/studio/ChannelsReviews";
import { BrandKitPanel } from "@/components/marketing/studio/BrandKitPanel";
import { AdsTab } from "@/components/marketing/studio/AdsTab";
import { ResultsTab } from "@/components/marketing/studio/ResultsTab";
import { STUDIO, btn, btnPrimary, studioError } from "@/components/marketing/studio/types";

const TABS = [
  { value: "agency", label: "Agency" }, { value: "approvals", label: "Approvals" }, { value: "research", label: "Research" },
  { value: "content", label: "Content" }, { value: "plan", label: "Plan" }, { value: "audit", label: "Audit" },
  { value: "results", label: "Results" }, { value: "ads", label: "Ads" }, { value: "reviews", label: "Reviews" }, { value: "library", label: "Library" }, { value: "profile", label: "Profile" },
];

export default function MarketingStudioPage() {
  // ?tab=research when Facebook Login sends the browser back here.
  const [tab, setTab] = useState(() => (typeof window !== "undefined" && new URLSearchParams(window.location.search).get("tab")) || "agency");
  const { data: session } = useSession();
  const isOwner = session?.user?.role === "owner";
  // The query cache is persisted to localStorage (lib/queryClient.ts), so the client can hold data the server render
  // did not have. Render the same skeleton as the server until mounted, or React reports a hydration mismatch.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  // A cheap read that answers "is the module on and may I see it?" before rendering the tabs.
  const gate = useQuery({ queryKey: ["studio-profile"], queryFn: () => api.get(`${STUDIO}/profile`).then(r => r.data), retry: false });
  const status = (gate.error as { response?: { status?: number; data?: { detail?: unknown } } } | null)?.response;
  const moduleOff = status?.status === 403 && JSON.stringify(status.data?.detail ?? "").includes("module_not_enabled");
  // Activation runs in the background and clears the workspace cache when done, so re-check a few times.
  const activate = useMutation({
    mutationFn: () => api.post("/workspace/modules/marketing_studio/activate"),
    onSuccess: () => { [3000, 8000, 20000].forEach(ms => setTimeout(() => gate.refetch(), ms)); },
  });

  return (
    <div className="h-full overflow-y-auto bg-[var(--haip-bg,var(--background))]">
      <div className="mx-auto max-w-[1280px] space-y-5 px-4 py-5 sm:px-6">
        <PageHeader title="Marketing Studio" subtitle="Plan, write and approve Instagram content"
          actions={<Link href="/dashboard/marketing" className={btn}>Ads results</Link>} />
        {!mounted || gate.isLoading ? <Skeleton className="h-40 w-full" /> : gate.isError ? (
          <Card>
            <EmptyState
              title={moduleOff ? "Marketing Studio is not switched on" : status?.status === 403 ? "Your role can't open Marketing Studio" : "Could not load Marketing Studio"}
              hint={moduleOff ? (isOwner ? "It needs a connected Instagram account for audits." : "Ask the workspace owner to switch it on.")
                : studioError(gate.error, "Try again in a moment.")}
              action={moduleOff && isOwner && (
                <button type="button" className={btnPrimary} disabled={activate.isPending || activate.isSuccess} onClick={() => activate.mutate()}>
                  {activate.isSuccess ? "Switching on…" : "Switch on Marketing Studio"}
                </button>
              )} />
          </Card>
        ) : (
          <>
            <Tabs label="Marketing Studio sections" value={tab} onChange={setTab} items={TABS} />
            {tab === "agency" && <AgencyTab />}
            {tab === "approvals" && <ApprovalsTab />}
            {tab === "research" && <ResearchTab />}
            {tab === "content" && <ContentTab />}
            {tab === "plan" && <PlanTab />}
            {tab === "audit" && <AuditTab />}
            {tab === "results" && <ResultsTab />}
            {tab === "ads" && <AdsTab />}
            {tab === "reviews" && <ReviewsTab />}
            {tab === "library" && <LibraryTab />}
            {tab === "profile" && <div className="space-y-4"><ProfileTab /><BrandKitPanel /></div>}
          </>
        )}
      </div>
    </div>
  );
}
