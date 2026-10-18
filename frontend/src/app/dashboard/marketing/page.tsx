"use client";
// Marketing: Meta ads next to what HAIP sees after the click. Spend, reach, clicks and "chats started" come from
// Meta; leads, bookings and revenue come from HAIP, joined by the ad that brought the guest in. Reads only.
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import api from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, DataTable, EmptyState, PageHeader, Stat, StatusPill, Tabs, type Column } from "@/components/ui/kit";
import { AccountPicker } from "@/components/marketing/AccountPicker";
import { BackfillPanel } from "@/components/marketing/BackfillPanel";
import { CampaignDrawer } from "@/components/marketing/CampaignDrawer";
import { DailyChart } from "@/components/marketing/DailyChart";
import {
  ago, errorText, money, money2, num, objectiveLabel, pct, statusLabel, times, type AdsStatus, type Campaign, type Summary,
} from "@/components/marketing/ads";

const RANGES = [{ value: "7", label: "7 days" }, { value: "30", label: "30 days" }, { value: "90", label: "90 days" }, { value: "365", label: "1 year" }];

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section aria-label={title} className="space-y-2">
      <h2 className="text-[13px] font-bold text-[var(--haip-fg)]">{title}</h2>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-6">{children}</div>
    </section>
  );
}

export default function MarketingPage() {
  const { data: session } = useSession();
  const role = session?.user?.role;
  const canChoose = role === "owner" || role === "manager";
  const qc = useQueryClient();
  const { toast } = useToast();
  const [days, setDays] = useState("30");
  const [open, setOpen] = useState<string | null>(null);

  const status = useQuery<AdsStatus>({
    queryKey: ["ads-status"], queryFn: () => api.get("/marketing/ads/status").then(r => r.data), staleTime: 30_000,
    // While a history load runs, poll so the progress bar moves; otherwise stay quiet.
    refetchInterval: q => (q.state.data?.backfill?.state === "queued" || q.state.data?.backfill?.state === "running" ? 3000 : false),
  });
  const s = status.data;
  const summary = useQuery<Summary>({
    queryKey: ["ads-summary", days], enabled: !!s?.configured, staleTime: 60_000, placeholderData: p => p,
    queryFn: () => api.get("/marketing/ads/summary", { params: { days } }).then(r => r.data),
  });

  // When a history load finishes, the numbers behind every range have changed.
  const lastState = useRef<string | undefined>(undefined);
  useEffect(() => {
    const now = s?.backfill?.state;
    if (lastState.current && lastState.current !== now && (now === "done" || now === "stopped")) {
      qc.invalidateQueries({ queryKey: ["ads-summary"] });
    }
    lastState.current = now;
  }, [s?.backfill?.state, qc]);

  const sync = useMutation({
    mutationFn: () => api.post("/marketing/ads/sync").then(r => r.data),
    onSuccess: r => {
      qc.invalidateQueries({ queryKey: ["ads-status"] });
      qc.invalidateQueries({ queryKey: ["ads-summary"] });
      toast({ variant: "success", title: "Ads updated", description: `${r.created} new and ${r.updated} refreshed rows, ${r.entities} campaign and ad details.` });
    },
    onError: e => toast({ variant: "error", title: "Could not update ads", description: errorText(e, "Try again in a few minutes.") }),
  });

  const t = summary.data?.totals;
  const rows = summary.data?.campaigns ?? [];
  const range = RANGES.find(r => r.value === days)?.label ?? "";
  const selected = rows.find(c => c.campaign_id === open) ?? null;

  const columns: Column<Campaign>[] = [
    { key: "name", header: "Campaign", cell: c => {
      const st = statusLabel(c.effective_status || c.status);
      const obj = objectiveLabel(c.objective);
      return (
        <div className="min-w-0">
          <p className="truncate font-semibold text-[var(--haip-fg)]">{c.campaign_name}</p>
          <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-[var(--haip-fg-subtle)]">
            {st && <StatusPill tone={st.tone}>{st.label}</StatusPill>}
            <span>{[obj, c.ads > 0 ? `${c.ads} ad${c.ads === 1 ? "" : "s"}` : "Not in synced ads"].filter(Boolean).join(" · ")}</span>
          </p>
        </div>);
    } },
    { key: "spend", header: "Spend", align: "right", cell: c => money(c.spend) },
    { key: "impr", header: "Shown", align: "right", hideBelow: "lg", cell: c => num(c.impressions) },
    { key: "clicks", header: "Clicks", align: "right", hideBelow: "md", cell: c => num(c.clicks) },
    { key: "ctr", header: "Click rate", align: "right", hideBelow: "lg", cell: c => pct(c.ctr) },
    { key: "conv", header: "Chats", align: "right", hideBelow: "sm", cell: c => num(c.meta_conversations) },
    { key: "cpc2", header: "Cost per chat", align: "right", hideBelow: "lg", cell: c => money2(c.cost_per_conversation) },
    { key: "leads", header: "Leads", align: "right", cell: c => num(c.haip_leads) },
    { key: "bookings", header: "Bookings", align: "right", hideBelow: "md", cell: c => num(c.bookings) },
    { key: "revenue", header: "Revenue", align: "right", hideBelow: "md", cell: c => money(c.revenue) },
    { key: "roas", header: "Return", align: "right", cell: c => <span className="font-semibold">{times(c.roas)}</span> },
  ];

  return (
    <div className="h-full overflow-y-auto bg-[var(--haip-bg,var(--background))]">
      <div className="mx-auto max-w-[1280px] space-y-5 px-4 py-5 sm:px-6">
        <PageHeader
          title="Marketing"
          subtitle={s?.ad_account ? `Meta ads · ${s.ad_account.name || s.ad_account.id} · updated ${ago(s.last_synced_at)}` : "What your Meta ads cost and what they bring in"}
          actions={(
            <>
              <Link href="/dashboard/marketing/studio" className="inline-flex h-9 items-center rounded-lg bg-primary px-3.5 text-[13px] font-semibold text-primary-foreground hover:opacity-90">Marketing Studio</Link>
              {s?.configured && <>
              <Tabs label="Date range" value={days} onChange={setDays} items={RANGES} />
              <button type="button" onClick={() => sync.mutate()} disabled={sync.isPending}
                className="h-9 rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-3.5 text-[13px] font-semibold text-[var(--haip-fg-2)] hover:bg-[var(--haip-surface)] disabled:opacity-50">
                {sync.isPending ? "Updating…" : "Update now"}
              </button>
              </>}
            </>
          )}
        />

        {!s && !status.isError ? (
          <Skeleton className="h-40 w-full" />
        ) : status.isError ? (
          <Card><EmptyState title="Could not load marketing data" hint={errorText(status.error, "You may not have access to this page.")} /></Card>
        ) : !s?.configured ? (
          <AccountPicker canChoose={canChoose} hasToken={!!s?.has_token} />
        ) : (
          <>
            {s.last_error && (
              <p role="alert" className="rounded-lg border border-[var(--haip-status-warning-border)] bg-[var(--haip-status-warning-bg)] px-3 py-2 text-sm text-[var(--haip-status-warning-fg)]">
                The last update from Meta failed: {s.last_error}
              </p>
            )}
            <BackfillPanel status={s} canStart={canChoose} />

            <Group title="What you paid for">
              <Stat label="Spend" value={money(t?.spend)} hint={range} loading={!t} />
              <Stat label="Shown" value={t ? num(t.impressions) : "—"} hint="impressions" loading={!t} />
              <Stat label="Clicks" value={t ? num(t.clicks) : "—"} hint={t ? `${num(t.link_clicks)} on links` : ""} loading={!t} />
              <Stat label="Click rate" value={pct(t?.ctr)} hint="clicks ÷ shown" loading={!t} />
              <Stat label="Per 1,000 shown" value={money2(t?.cpm)} hint="cost (CPM)" loading={!t} />
              <Stat label="Per click" value={money2(t?.cpc)} hint="cost (CPC)" loading={!t} />
            </Group>

            <Group title="What it brought in">
              <Stat label="Chats started" value={t ? num(t.meta_conversations) : "—"} hint="counted by Meta" loading={!t} />
              <Stat label="Cost per chat" value={money2(t?.cost_per_conversation)} hint="spend ÷ chats" loading={!t} />
              <Stat label="Leads in HAIP" value={t ? num(t.haip_leads) : "—"} hint="traced to these ads" loading={!t} />
              <Stat label="Bookings" value={t ? num(t.bookings) : "—"} hint="from those leads" loading={!t} />
              <Stat label="Revenue" value={money(t?.revenue)} hint="from those bookings" loading={!t} />
              <Stat label="Return on spend" value={times(t?.roas)} hint={t?.roas == null ? "needs spend" : "revenue ÷ spend"} loading={!t} />
            </Group>

            <Group title="Engagement">
              <Stat label="Engagements" value={t ? num(t.post_engagement) : "—"} hint="reactions, comments, shares" loading={!t} />
              <Stat label="Video views" value={t ? num(t.video_views) : "—"} hint={range} loading={!t} />
              <Stat label="First replies" value={t ? num(t.first_replies) : "—"} hint="chats we answered" loading={!t} />
            </Group>

            {t && t.attribution_gap > 0 && (
              <p className="rounded-lg border border-[var(--haip-border)] bg-[var(--haip-surface)] px-3 py-2 text-sm text-[var(--haip-fg-2)]">
                Meta counted {num(t.meta_conversations)} chats started, and HAIP traced {num(t.haip_conversations)} to an ad.{" "}
                {num(t.attribution_gap)} could not be linked, so leads and revenue here are a floor, not the full picture.
              </p>
            )}

            {summary.isError ? (
              <Card><EmptyState title="Could not load the summary" hint={errorText(summary.error, "Try again.")} /></Card>
            ) : t && rows.length === 0 ? (
              <Card><EmptyState title="No ad data yet" hint="Nothing ran in this period, or the first update has not finished. Use Update now, or Load history above." /></Card>
            ) : (
              <>
                {summary.data && <DailyChart daily={summary.data.daily} rangeLabel={range} />}
                <p className="text-xs text-[var(--haip-fg-subtle)]">Select a campaign to see its ads, audience and every number.</p>
                <DataTable<Campaign> columns={columns} rows={rows} rowKey={c => c.campaign_id} loading={!summary.data}
                  onRowClick={c => setOpen(c.campaign_id)} maxHeightClass="max-h-none"
                  empty={{ title: "No campaigns", hint: "Campaigns appear after the first update." }} />
              </>
            )}
          </>
        )}
      </div>
      <CampaignDrawer campaign={selected} rangeLabel={range} onClose={() => setOpen(null)} />
    </div>
  );
}
