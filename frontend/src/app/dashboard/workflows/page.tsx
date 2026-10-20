"use client";
// Lead workflows: the ready-made playbooks that make sure no lead goes unnoticed, in three tabs:
//   Playbooks  switches, modes, team alerts, WhatsApp templates      (components/workflows/PlaybooksTab.tsx)
//   Activity   what the playbooks did, skipped or held, and why      (components/workflows/ActivityTab.tsx)
//   Report     leads received in a period: funnel + one row per agent (components/workflows/ReportTab.tsx)
// Owner and manager only. A bare "#activity" / "#report" in the link opens that tab.
import { useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { PageHeader, Tabs } from "@/components/ui/kit";
import { ActivityTab } from "@/components/workflows/ActivityTab";
import { PlaybooksTab } from "@/components/workflows/PlaybooksTab";
import { ReportTab } from "@/components/workflows/ReportTab";

const TABS = [{ value: "playbooks", label: "Playbooks" }, { value: "activity", label: "Activity" }, { value: "report", label: "Report" }];

export default function WorkflowsPage() {
  const { data: session } = useSession();
  const role = session?.user?.role;
  const [tab, setTab] = useState("playbooks");
  useEffect(() => {
    const h = window.location.hash.replace("#", "");
    if (TABS.some(t => t.value === h)) setTab(h);
  }, []);
  const pick = (v: string) => {
    setTab(v);
    try { window.history.replaceState(null, "", v === "playbooks" ? window.location.pathname : `#${v}`); } catch { /* not important */ }
  };

  if (role && role !== "owner" && role !== "manager") {
    return <div className="p-8 text-sm text-[var(--haip-fg-muted)]">Only an owner or manager can see lead workflows.</div>;
  }
  return (
    <div className="h-full overflow-y-auto bg-[var(--haip-bg,var(--background))]">
      <div className={`mx-auto space-y-5 px-4 py-6 sm:px-6 ${tab === "report" ? "max-w-5xl" : "max-w-3xl"}`}>
        <PageHeader title="Lead workflows"
          subtitle="Automatic steps so no lead goes unnoticed. Each one is off until you switch it on." />
        <Tabs items={TABS} value={tab} onChange={pick} label="Lead workflows" />
        {!role ? null : tab === "playbooks" ? <PlaybooksTab /> : tab === "activity" ? <ActivityTab /> : <ReportTab />}
      </div>
    </div>
  );
}
