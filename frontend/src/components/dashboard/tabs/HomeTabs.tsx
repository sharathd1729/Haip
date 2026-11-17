"use client";
// Home's dashboard tabs (workspace redesign Phase 2): Overview, Leads & sales, Bookings & payments, Ops, Revenue, Marketing,
// Team. The open tab lives in ?tab= so a link, a refresh and Back keep it. A tab the person can't use is not offered.
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useSession } from "next-auth/react";
import { cn } from "@/lib/utils";
import { BOOKING_READ_ROLES, REVENUE_READ_ROLES } from "@/lib/permissions";
import { OPS_BUSINESS_TYPES } from "@/lib/segments";
import { useBusinessType } from "@/components/providers/WorkspaceProvider";

export type HomeTab = "overview" | "leads" | "bookings" | "ops" | "revenue" | "marketing" | "team";

const ALL: { value: HomeTab; label: string }[] = [
  { value: "overview", label: "Overview" },
  { value: "leads", label: "Leads & sales" },
  { value: "bookings", label: "Bookings & payments" },
  { value: "ops", label: "Ops" },
  { value: "revenue", label: "Revenue" },
  { value: "marketing", label: "Marketing" },
  { value: "team", label: "Team" },
];

export function useHomeTab(): { tab: HomeTab; tabs: typeof ALL; setTab: (t: HomeTab) => void } {
  const role = (useSession().data?.user as { role?: string } | undefined)?.role ?? "";
  const businessType = useBusinessType();
  const params = useSearchParams();
  const router = useRouter();
  const path = usePathname() ?? "";
  const tabs = ALL.filter(t =>
    (t.value !== "bookings" || (BOOKING_READ_ROLES as string[]).includes(role))
    && (t.value !== "revenue" || (REVENUE_READ_ROLES as string[]).includes(role))
    && (t.value !== "ops" || (!!businessType && OPS_BUSINESS_TYPES.includes(businessType))));
  const want = params?.get("tab");
  const tab = (tabs.find(t => t.value === want)?.value ?? "overview") as HomeTab;
  const setTab = (t: HomeTab) => router.replace(t === "overview" ? path : `${path}?tab=${t}`, { scroll: false });
  return { tab, tabs, setTab };
}

export function HomeTabBar({ tab, tabs, setTab }: ReturnType<typeof useHomeTab>) {
  return (
    <nav aria-label="Dashboards" className="-mx-3 overflow-x-auto px-3 sm:mx-0 sm:px-0">
      <div className="inline-flex gap-1 rounded-full bg-[var(--haip-tabs-track,var(--haip-surface))] p-1">
        {tabs.map(t => (
          <button key={t.value} type="button" onClick={() => setTab(t.value)} aria-current={tab === t.value ? "page" : undefined}
            className={cn("min-h-10 whitespace-nowrap rounded-full px-4 text-[14px] font-medium transition-colors active:scale-[0.97]",
              tab === t.value ? "bg-primary font-semibold text-primary-foreground" : "text-[var(--haip-fg-2)] hover:bg-[var(--haip-nav-hover)]")}>
            {t.label}
          </button>
        ))}
      </div>
    </nav>
  );
}
