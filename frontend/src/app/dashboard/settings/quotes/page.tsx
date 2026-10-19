"use client";
// Settings > Quotes (owner / manager): the packages and routes the rate calculator prices from (versioned business records:
// a change is a new version, drafts wait for approval), the WhatsApp quote templates, and the quote defaults (GST, advance,
// validity, the owner-OK limit). Moved here from the old Quotes page tabs so the calculator stays one simple page.
import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import { AlertCircle } from "@/lib/icons";
import api from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, EmptyState, PageHeader, Tabs } from "@/components/ui/kit";
import { PackagesTab } from "@/components/quotes/PackagesTab";
import { RoutesTab } from "@/components/quotes/RoutesTab";
import { MessagesTab } from "@/components/quotes/MessagesTab";
import { QuoteDefaultsCard } from "@/components/quotes/QuoteDefaultsCard";
import { BTN_GHOST } from "@/components/quotes/ui";
import type { Catalog } from "@/app/dashboard/quotes/types";

type Tab = "packages" | "routes" | "messages" | "defaults";

export default function QuoteSettingsPage() {
  const { data: session } = useSession();
  const role = (session?.user as { role?: string } | undefined)?.role;
  const allowed = role === "owner" || role === "manager";
  const [tab, setTab] = useState<Tab>("packages");
  const catalog = useQuery<Catalog>({ queryKey: ["quote-catalog"], queryFn: () => api.get("/quotes/catalog").then(r => r.data), retry: 1, enabled: allowed });

  if (session && !allowed) {
    return (
      <div className="mx-auto w-full max-w-5xl px-4 py-6 sm:px-6">
        <Card><EmptyState title="Only the owner or a manager can change packages and quote settings" hint="Ask them to update a price or a route." /></Card>
      </div>
    );
  }
  return (
    <div className="mx-auto w-full max-w-7xl space-y-4 px-4 py-4 sm:px-6 sm:py-6">
      <PageHeader title="Packages and routes" subtitle="What the rate calculator prices from. Both caravans cost the same; quotes already saved keep their prices."
        actions={<Link href="/dashboard/quotes" className={BTN_GHOST}>Open the rate calculator</Link>} />
      <Tabs label="Quote settings" value={tab} onChange={v => setTab(v as Tab)}
        items={[{ value: "packages", label: "Packages" }, { value: "routes", label: "Routes" }, { value: "messages", label: "WhatsApp messages" },
          { value: "defaults", label: "Defaults" }]} />
      {tab === "defaults" ? <QuoteDefaultsCard /> : catalog.isPending ? (
        <div className="space-y-3">{[1, 2, 3].map(i => <Skeleton key={i} className="h-28 rounded-2xl" />)}</div>
      ) : catalog.isError || !catalog.data ? (
        <div role="alert" className="flex items-start gap-3 rounded-xl border border-[var(--haip-status-danger-border)] bg-[var(--haip-status-danger-bg)] px-4 py-3 text-sm text-[var(--haip-status-danger-fg)]">
          <AlertCircle size={16} className="mt-0.5 shrink-0" />
          <span className="flex-1">Couldn&apos;t load the packages and routes.</span>
          <button type="button" onClick={() => catalog.refetch()} className="min-h-11 rounded-lg border border-current px-3 text-xs font-semibold sm:min-h-9">Try again</button>
        </div>
      ) : tab === "packages" ? <PackagesTab catalog={catalog.data} />
        : tab === "routes" ? <RoutesTab catalog={catalog.data} />
        : <MessagesTab catalog={catalog.data} />}
    </div>
  );
}
