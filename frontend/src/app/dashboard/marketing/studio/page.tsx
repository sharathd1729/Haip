"use client";
// Marketing Studio: setup + the AI agency (Home), insights, plan, create, publish (scheduling, posting to Instagram,
// Facebook and Google, ads) and settings. Server-side gates: module marketing_studio + marketing.* capabilities; this
// page only mirrors them. The section is the URL's ?tab= (a leaf such as "library"), so banners and the setup checklist
// can deep-link to the exact place to fix something.
import Link from "next/link";
import { Suspense, useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import api from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, EmptyState, PageHeader, Tabs } from "@/components/ui/kit";
import { ContentTab } from "@/components/marketing/studio/ContentTab";
import { HomeTab } from "@/components/marketing/studio/HomeTab";
import { ApprovalsTab } from "@/components/marketing/studio/ApprovalsTab";
import { ResearchTab } from "@/components/marketing/studio/ResearchTab";
import { AuditTab, PlanTab } from "@/components/marketing/studio/InsightsTabs";
import { LibraryTab, ProfileTab } from "@/components/marketing/studio/ProfileLibraryTabs";
import { ReviewsTab } from "@/components/marketing/studio/ChannelsReviews";
import { BrandKitPanel } from "@/components/marketing/studio/BrandKitPanel";
import { AdsTab } from "@/components/marketing/studio/AdsTab";
import { ResultsTab } from "@/components/marketing/studio/ResultsTab";
import { PartnersTab } from "@/components/marketing/studio/PartnersTab";
import { STUDIO, btn, btnPrimary, studioError } from "@/components/marketing/studio/types";

/** Six sections, each grouping the older tabs (nothing removed). The first leaf opens when a section is picked. */
const GROUPS: { value: string; label: string; leaves: { value: string; label: string }[] }[] = [
  { value: "home", label: "Home", leaves: [{ value: "home", label: "Overview" }] },
  { value: "insights", label: "Insights", leaves: [{ value: "results", label: "Results" }, { value: "audit", label: "Audit" }] },
  { value: "plan", label: "Plan", leaves: [{ value: "plan", label: "Plan" }, { value: "research", label: "Research" }] },
  { value: "create", label: "Create", leaves: [{ value: "content", label: "Content" }, { value: "library", label: "Library" }, { value: "partners", label: "Partners" }] },
  { value: "publish", label: "Publish", leaves: [{ value: "approvals", label: "Approvals" }, { value: "ads", label: "Ads" }, { value: "reviews", label: "Reviews" }] },
  { value: "settings", label: "Settings", leaves: [{ value: "profile", label: "Brand" }] },
];
const ALIASES: Record<string, string> = { agency: "home" };       // older links (?tab=agency) land on Home
const groupOf = (leaf: string) => GROUPS.find(g => g.leaves.some(l => l.value === leaf)) ?? GROUPS[0];

const ACTIVATION_POLL_MS = 2000;
const ACTIVATION_MAX_TRIES = 30;                                   // about a minute, then say so

function Studio() {
  const params = useSearchParams();
  const router = useRouter();
  const path = usePathname();
  const asked = params.get("tab") ?? "home";
  const leaf = GROUPS.some(g => g.leaves.some(l => l.value === (ALIASES[asked] ?? asked))) ? (ALIASES[asked] ?? asked) : "home";
  const group = groupOf(leaf);
  const go = (v: string) => router.replace(`${path}?tab=${encodeURIComponent(v)}`, { scroll: false });
  const { data: session } = useSession();
  const isOwner = session?.user?.role === "owner";
  // The query cache is persisted to localStorage (lib/queryClient.ts), so the client can hold data the server render
  // did not have. Render the same skeleton as the server until mounted, or React reports a hydration mismatch.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  // Activation runs in the background; poll the module gate until it opens (bounded), instead of guessing delays.
  const [polling, setPolling] = useState(false);
  const [tries, setTries] = useState(0);
  const gate = useQuery({
    queryKey: ["studio-profile"], queryFn: () => api.get(`${STUDIO}/profile`).then(r => r.data), retry: false,
    refetchInterval: polling ? ACTIVATION_POLL_MS : false,
  });
  useEffect(() => {
    if (!polling) return;
    if (gate.isSuccess || tries >= ACTIVATION_MAX_TRIES) setPolling(false);
  }, [polling, gate.isSuccess, tries]);
  useEffect(() => { if (polling) setTries(t => t + 1); }, [polling, gate.dataUpdatedAt, gate.errorUpdatedAt]);
  const status = (gate.error as { response?: { status?: number; data?: { detail?: unknown } } } | null)?.response;
  const moduleOff = status?.status === 403 && JSON.stringify(status.data?.detail ?? "").includes("module_not_enabled");
  const activate = useMutation({
    mutationFn: () => api.post("/workspace/modules/marketing_studio/activate"),
    onSuccess: () => { setTries(0); setPolling(true); },
  });
  const gaveUp = activate.isSuccess && !polling && tries >= ACTIVATION_MAX_TRIES && !gate.isSuccess;

  return (
    <div className="h-full overflow-y-auto bg-[var(--haip-bg,var(--background))]">
      <div className="mx-auto max-w-[1280px] space-y-5 px-4 py-5 sm:px-6">
        <PageHeader title="Marketing Studio" subtitle="Plan, create, approve and post your marketing"
          actions={<Link href="/dashboard/marketing" className={btn}>Ads results</Link>} />
        {!mounted || gate.isLoading ? <Skeleton className="h-40 w-full" /> : gate.isError ? (
          <Card>
            <EmptyState
              title={moduleOff ? "Marketing Studio is not switched on" : status?.status === 403 ? "Your role can't open Marketing Studio" : "Could not load Marketing Studio"}
              hint={gaveUp ? "Switching on is taking longer than usual. Refresh the page in a minute."
                : moduleOff ? (isOwner ? "It needs a connected Instagram account for audits." : "Ask the workspace owner to switch it on.")
                : studioError(gate.error, "Try again in a moment.")}
              action={moduleOff && isOwner && (
                <button type="button" className={btnPrimary} disabled={activate.isPending || polling} onClick={() => activate.mutate()}>
                  {activate.isPending || polling ? "Switching on…" : "Switch on Marketing Studio"}
                </button>
              )} />
          </Card>
        ) : (
          <>
            <Tabs label="Marketing Studio sections" value={group.value} onChange={v => go(GROUPS.find(g => g.value === v)!.leaves[0].value)}
              items={GROUPS.map(g => ({ value: g.value, label: g.label }))} />
            {group.leaves.length > 1 && (
              <Tabs label={`${group.label} sections`} value={leaf} onChange={go} items={group.leaves} className="-mt-2" />
            )}
            {leaf === "home" && <HomeTab />}
            {leaf === "approvals" && <ApprovalsTab />}
            {leaf === "research" && <ResearchTab />}
            {leaf === "content" && <ContentTab />}
            {leaf === "plan" && <PlanTab />}
            {leaf === "audit" && <AuditTab />}
            {leaf === "results" && <ResultsTab />}
            {leaf === "partners" && <PartnersTab />}
            {leaf === "ads" && <AdsTab />}
            {leaf === "reviews" && <ReviewsTab />}
            {leaf === "library" && <LibraryTab />}
            {leaf === "profile" && <div className="space-y-4"><ProfileTab /><BrandKitPanel /></div>}
          </>
        )}
      </div>
    </div>
  );
}

export default function MarketingStudioPage() {
  return <Suspense fallback={<Skeleton className="m-5 h-40" />}><Studio /></Suspense>;
}
