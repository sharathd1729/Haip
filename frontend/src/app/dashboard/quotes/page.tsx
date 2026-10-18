"use client";
// Quote builder, layout B (docs/design/bookings-mockup/quotes.html): everything on one page, the quote card always current.
// Tabs: New quote | Routes | Packages | WhatsApp messages (owner/manager: the four templates' Meta status, "Create drafts").
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertCircle } from "@/lib/icons";
import api from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, EmptyState, PageHeader, Tabs } from "@/components/ui/kit";
import { QuoteBuilder } from "@/components/quotes/QuoteBuilder";
import { RoutesTab } from "@/components/quotes/RoutesTab";
import { PackagesTab } from "@/components/quotes/PackagesTab";
import { MessagesTab } from "@/components/quotes/MessagesTab";
import type { Catalog } from "./types";

type Tab = "new" | "routes" | "packages" | "messages";

export default function QuotesPage() {
  const [tab, setTab] = useState<Tab>("new");
  const [useRoute, setUseRoute] = useState<string | null>(null);
  const catalog = useQuery<Catalog>({ queryKey: ["quote-catalog"], queryFn: () => api.get("/quotes/catalog").then(r => r.data), retry: 1 });
  const status = (catalog.error as { response?: { status?: number } } | null)?.response?.status;

  return (
    <div className="mx-auto w-full max-w-7xl space-y-4 px-4 py-4 sm:px-6 sm:py-6">
      <PageHeader title="Quotes" subtitle="Price a trip from the published rate card, save it to the lead, and keep routes and packages up to date." />
      <Tabs label="Quotes" value={tab} onChange={v => setTab(v as Tab)}
        items={[{ value: "new", label: "New quote" }, { value: "routes", label: "Routes" }, { value: "packages", label: "Packages" },
          ...(catalog.data?.permissions.can_manage_templates ? [{ value: "messages", label: "WhatsApp messages" }] : [])]} />

      {/* isPending, not isLoading: on the server the query has not started fetching, so isLoading is false there and the
          error branch would render, then mismatch the browser's skeleton (hydration error). */}
      {catalog.isPending ? (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_380px]">
          <div className="space-y-3">{[1, 2, 3].map(i => <Skeleton key={i} className="h-36 rounded-2xl" />)}</div>
          <Skeleton className="h-80 rounded-2xl" />
        </div>
      ) : catalog.isError || !catalog.data ? (
        status === 403 ? (
          <Card><EmptyState title="Quotes are not open to your role" hint="Ask the owner to give your role the quotes permission in Roles & permissions." /></Card>
        ) : (
          <div role="alert" className="flex items-start gap-3 rounded-xl border border-[var(--haip-status-danger-border)] bg-[var(--haip-status-danger-bg)] px-4 py-3 text-sm text-[var(--haip-status-danger-fg)]">
            <AlertCircle size={16} className="mt-0.5 shrink-0" />
            <span className="flex-1">Couldn&apos;t load the rate card.</span>
            <button onClick={() => catalog.refetch()} className="min-h-11 rounded-lg border border-current px-3 text-xs font-semibold sm:min-h-9">Try again</button>
          </div>
        )
      ) : tab === "new" ? (
        <QuoteBuilder catalog={catalog.data} startRoute={useRoute} onRouteUsed={() => setUseRoute(null)} onOpenPackages={() => setTab("packages")} />
      ) : tab === "routes" ? (
        <RoutesTab catalog={catalog.data} onQuote={key => { setUseRoute(key); setTab("new"); }} />
      ) : tab === "packages" ? (
        <PackagesTab catalog={catalog.data} />
      ) : (
        <MessagesTab catalog={catalog.data} />
      )}
    </div>
  );
}
