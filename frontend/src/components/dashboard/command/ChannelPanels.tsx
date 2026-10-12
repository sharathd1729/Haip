"use client";
// Instagram profile activity and WhatsApp campaign results, read from the existing Instagram Insights and WhatsApp
// overview APIs. Both look at the LAST 30 DAYS, not the period selected above, and say so. They load after the main
// numbers, each on its own, so a slow or disconnected channel never blocks or breaks the page.
import type { ReactNode } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";
import { NotAvailable, Row, SectionTitle } from "./parts";
import { num, pct } from "./types";

interface InstagramResponse {
  connected: boolean;
  overview: { followers_count: number | null; accounts_engaged: number | null; total_interactions: number | null; profile_links_taps: number | null;
    likes: number | null; comments: number | null } | null;
  trend: { date: string; reach: number | null; profile_views: number | null }[];
}
interface WhatsAppResponse {
  totals: { sent: number; delivered: number; read: number; failed: number; delivery_rate: number | null; read_rate: number | null; failure_rate: number | null; campaigns: number; opt_outs: number };
  health: { connected: boolean };
}

function Panel({ id, title, sub, href, hrefLabel, children }: { id: string; title: string; sub: string; href: string; hrefLabel: string; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className="haip-card min-w-0 px-4 py-4 sm:px-6 sm:py-5">
      <SectionTitle sub={sub} actions={<Link href={href} className="inline-flex min-h-11 items-center text-[12.5px] font-semibold text-primary hover:underline lg:min-h-0">{hrefLabel}</Link>}>
        <span id={id}>{title}</span>
      </SectionTitle>
      {children}
    </section>
  );
}

function Loading() { return <div className="space-y-2" aria-busy="true"><Skeleton className="h-5 w-full" /><Skeleton className="h-5 w-4/5" /><Skeleton className="h-5 w-3/5" /></div>; }

function Instagram({ enabled }: { enabled: boolean }) {
  const q = useQuery<InstagramResponse>({
    queryKey: ["oc-instagram-insights"], enabled, staleTime: 5 * 60_000, retry: false,
    queryFn: () => api.get("/instagram-insights", { params: { range_days: 30 } }).then(r => r.data),
  });
  const reach = (q.data?.trend ?? []).reduce((a, p) => a + (p.reach ?? 0), 0);
  const views = (q.data?.trend ?? []).reduce((a, p) => a + (p.profile_views ?? 0), 0);
  const o = q.data?.overview;
  return (
    <Panel id="ig-title" title="Instagram" sub="Last 30 days, not the period above" href="/dashboard/instagram-insights" hrefLabel="Instagram Insights">
      {q.isLoading || !enabled ? <Loading /> : q.isError ? <NotAvailable label="Instagram" reason="The insights could not be loaded. Check the connection under Settings, Integrations." />
        : !q.data?.connected || !o ? <NotAvailable label="Instagram" reason="No Instagram account is connected." /> : (
          <dl className="divide-y divide-[var(--haip-border)]">
            <Row label="Followers" value={num(o.followers_count)} />
            <Row label="Reach" value={num(reach)} hint="people who saw your content" />
            <Row label="Profile views" value={num(views)} />
            <Row label="Accounts engaged" value={num(o.accounts_engaged)} />
            <Row label="Interactions" value={num(o.total_interactions)} hint={`${num(o.likes)} likes · ${num(o.comments)} comments`} />
            <Row label="Bio link taps" value={num(o.profile_links_taps)} />
          </dl>
        )}
    </Panel>
  );
}

function WhatsApp({ enabled }: { enabled: boolean }) {
  const q = useQuery<WhatsAppResponse>({
    queryKey: ["oc-wa-analytics"], enabled, staleTime: 5 * 60_000, retry: false,
    queryFn: () => api.get("/messaging/analytics", { params: { days: 30 } }).then(r => r.data),
  });
  const t = q.data?.totals;
  return (
    <Panel id="wa-title" title="WhatsApp campaigns" sub="Last 30 days, not the period above" href="/dashboard/messaging" hrefLabel="WhatsApp overview">
      {q.isLoading || !enabled ? <Loading /> : q.isError ? <NotAvailable label="WhatsApp campaigns" reason="The results could not be loaded, or your role cannot see campaign reports." />
        : !t ? <NotAvailable label="WhatsApp campaigns" reason="No campaign data." /> : t.sent + t.failed === 0 ? (
          <p className="py-4 text-[13px] text-[var(--haip-fg-subtle)]">No campaign messages were sent in the last 30 days.</p>
        ) : (
          <dl className="divide-y divide-[var(--haip-border)]">
            <Row label="Sent" value={num(t.sent)} hint={`across ${num(t.campaigns)} campaign${t.campaigns === 1 ? "" : "s"}`} />
            <Row label="Delivered" value={pct(t.delivery_rate)} hint={`${num(t.delivered)} messages`} />
            <Row label="Read" value={pct(t.read_rate)} hint={`${num(t.read)} messages`} />
            <Row label="Failed" value={pct(t.failure_rate)} hint={`${num(t.failed)} messages`} tone={(t.failure_rate ?? 0) >= 5 ? "warning" : undefined} />
            <Row label="Opted out" value={num(t.opt_outs)} muted />
          </dl>
        )}
    </Panel>
  );
}

export function ChannelPanels({ ready }: { ready: boolean }) {
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
      <Instagram enabled={ready} />
      <WhatsApp enabled={ready} />
    </div>
  );
}
