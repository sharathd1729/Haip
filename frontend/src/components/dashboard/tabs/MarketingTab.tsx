"use client";
// Home › Marketing (workspace redesign Phase 2): Meta ads for the last 30 days next to what they brought in
// (GET /marketing/ads/summary, the same numbers as the Marketing page), and where this period's leads came from.
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { Card, CardBody, CardHeader, EmptyState, Stat } from "@/components/ui/kit";
import { money, num, times, type AdsStatus, type Summary } from "@/components/marketing/ads";
import { SourcesCard } from "@/components/dashboard/command/LeadsRow";
import type { Overview } from "@/components/dashboard/command/CommandCenter";

export function MarketingTab({ data, period }: { data: Overview; period: string }) {
  const status = useQuery<AdsStatus>({ queryKey: ["ads-status"], queryFn: () => api.get("/marketing/ads/status").then(r => r.data), staleTime: 30_000 });
  const summary = useQuery<Summary>({
    queryKey: ["ads-summary", "30"], queryFn: () => api.get("/marketing/ads/summary", { params: { days: 30 } }).then(r => r.data),
    enabled: !!status.data?.configured, staleTime: 5 * 60_000,
  });
  const t = summary.data?.totals;
  return (
    <div className="space-y-4">
      {status.isError ? null : !status.data?.configured ? (
        <Card><EmptyState title="Meta ads aren't connected" hint="Connect your ad account to see what ads cost and what they bring in."
          action={<Link href="/dashboard/marketing" className="inline-flex min-h-11 items-center rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground">Open Marketing</Link>} /></Card>
      ) : (
        <Card>
          <CardHeader title="Meta ads" description="Last 30 days"
            actions={<Link href="/dashboard/marketing" className="text-sm font-semibold text-primary hover:underline">Campaigns</Link>} />
          <CardBody>
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
              <Stat label="Spend" value={money(t?.spend)} loading={!t} />
              <Stat label="Chats started" value={t ? num(t.meta_conversations) : "—"} loading={!t} />
              <Stat label="Leads" value={t ? num(t.haip_leads) : "—"} hint="with a phone number" loading={!t} />
              <Stat label="Bookings" value={t ? num(t.bookings) : "—"} loading={!t} />
              <Stat label="Return on spend" value={t ? times(t.roas) : "—"} hint="revenue ÷ spend" loading={!t} />
            </div>
          </CardBody>
        </Card>
      )}
      <SourcesCard sources={data.sources} period={period} />
      <div className="flex flex-wrap gap-2 text-sm">
        {[["WhatsApp campaigns", "/dashboard/messaging/campaigns"], ["Growth tools", "/dashboard/messaging/growth"],
          ["Instagram insights", "/dashboard/instagram-insights"], ["Website", "/dashboard/marketing/website"]].map(([label, href]) => (
          <Link key={href} href={href} className="inline-flex min-h-11 items-center rounded-full border border-[var(--haip-border)] bg-[var(--haip-card)] px-4 font-semibold text-[var(--haip-fg-2)] hover:bg-[var(--haip-surface)]">{label}</Link>
        ))}
      </div>
    </div>
  );
}
