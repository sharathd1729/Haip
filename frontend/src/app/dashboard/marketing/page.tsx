"use client";
// Marketing: Meta ads next to what HAIP sees after the click. Spend and "conversations started" come from
// Meta; leads, bookings and revenue come from HAIP, joined by the ad that brought the guest in. Reads only.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import api from "@/lib/api";
import { cn, formatINR } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardBody, CardHeader, DataTable, EmptyState, PageHeader, Stat, Tabs, type Column } from "@/components/ui/kit";

interface AdsStatus {
  configured: boolean; has_token: boolean; token_source: string | null;
  ad_account: { id: string; name: string | null; currency: string | null } | null;
  last_synced_at: string | null; last_error: string | null;
}
interface Campaign {
  campaign_id: string; campaign_name: string; spend: number; impressions: number; reach: number; clicks: number; ads: number;
  meta_conversations: number; haip_conversations: number; haip_leads: number; bookings: number; revenue: number;
  cost_per_conversation: number | null; cost_per_lead: number | null; roas: number | null;
}
interface Summary {
  since: string; until: string; days: number; currency: string;
  totals: {
    spend: number; impressions: number; reach: number; clicks: number; meta_conversations: number; haip_conversations: number;
    haip_leads: number; bookings: number; revenue: number; cost_per_conversation: number | null; cost_per_lead: number | null;
    roas: number | null; attribution_gap: number;
  };
  campaigns: Campaign[]; daily: { date: string; spend: number; conversations: number }[];
}
interface AdAccount { id: string; name: string; currency: string; status: number | null }

const RANGES = [{ value: "7", label: "7 days" }, { value: "30", label: "30 days" }, { value: "90", label: "90 days" }];

const num = (n: number) => new Intl.NumberFormat("en-IN").format(n);
const money = (n: number | null | undefined) => (n == null ? "—" : formatINR(n));
const roas = (n: number | null | undefined) => (n == null ? "—" : `${n.toFixed(1)}×`);

function errorText(e: unknown, fallback: string): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof d === "string" ? d : fallback;
}

function ago(iso: string | null): string {
  if (!iso) return "never";
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 2) return "just now";
  if (m < 60) return `${m} minutes ago`;
  const h = Math.floor(m / 60);
  return h < 24 ? `${h} hours ago` : `${Math.floor(h / 24)} days ago`;
}

const shortDate = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short" });

/** Daily spend as bars. Direct label for the busiest day instead of a legend; one series needs none. */
function SpendBars({ daily }: { daily: Summary["daily"] }) {
  if (daily.length === 0) return null;
  const max = Math.max(...daily.map(d => d.spend), 1);
  const W = 600, H = 120, gap = 3;
  const bw = Math.max(2, (W - gap * (daily.length - 1)) / daily.length);
  const top = daily.reduce((a, b) => (b.spend > a.spend ? b : a));
  return (
    <figure className="m-0">
      <svg viewBox={`0 0 ${W} ${H + 18}`} className="w-full" role="img"
        aria-label={`Daily ad spend. Highest day ${shortDate(top.date)}, ${formatINR(top.spend)}.`}>
        {[0.5, 1].map(f => (
          <line key={f} x1={0} x2={W} y1={H - H * f} y2={H - H * f} className="stroke-[var(--haip-border)]" strokeWidth={1} />
        ))}
        {daily.map((d, i) => {
          const h = Math.max(1, (d.spend / max) * (H - 4));
          return (
            <rect key={d.date} x={i * (bw + gap)} y={H - h} width={bw} height={h} rx={2}
              className={d === top ? "fill-primary" : "fill-primary/45"}>
              <title>{`${shortDate(d.date)}: ${formatINR(d.spend)}, ${d.conversations} chats started`}</title>
            </rect>
          );
        })}
        <text x={0} y={H + 14} className="fill-[var(--haip-fg-subtle)] text-[11px]">{shortDate(daily[0].date)}</text>
        <text x={W} y={H + 14} textAnchor="end" className="fill-[var(--haip-fg-subtle)] text-[11px]">{shortDate(daily[daily.length - 1].date)}</text>
      </svg>
      <figcaption className="mt-1 text-xs text-[var(--haip-fg-subtle)]">Highest day: {formatINR(top.spend)} on {shortDate(top.date)}</figcaption>
    </figure>
  );
}

function AccountPicker({ canChoose, hasToken }: { canChoose: boolean; hasToken: boolean }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [picked, setPicked] = useState("");
  const accounts = useQuery<{ accounts: AdAccount[] }>({
    queryKey: ["ads-accounts"], enabled: canChoose && hasToken, retry: false,
    queryFn: () => api.get("/marketing/ads/accounts").then(r => r.data),
  });
  const choose = useMutation({
    mutationFn: (id: string) => api.put("/marketing/ads/account", { ad_account_id: id }).then(r => r.data),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["ads-status"] });
      toast({ variant: "success", title: "Ad account chosen", description: "Pulling the last 30 days now." });
      api.post("/marketing/ads/sync").finally(() => qc.invalidateQueries({ queryKey: ["ads-summary"] }));
    },
    onError: e => toast({ variant: "error", title: "Could not choose that account", description: errorText(e, "Try again.") }),
  });

  if (!hasToken) {
    return <EmptyState title="Connect WhatsApp first" hint="Meta ads use the same Meta access token as your WhatsApp connection, and none is saved yet. Add it under Settings, Integrations." />;
  }
  if (!canChoose) {
    return <EmptyState title="No ad account chosen yet" hint="Ask an owner or manager to choose which Meta ad account to show here." />;
  }
  return (
    <Card>
      <CardHeader title="Choose your ad account" description="These are the ad accounts your Meta access token can read. Nothing is changed in Meta." />
      <CardBody className="space-y-3">
        {accounts.isLoading && <Skeleton className="h-16 w-full" />}
        {accounts.isError && <p className="text-sm text-[var(--haip-status-danger-fg)]">{errorText(accounts.error, "Could not load ad accounts.")}</p>}
        {accounts.data?.accounts.length === 0 && <p className="text-sm text-[var(--haip-fg-subtle)]">This token cannot see any ad account. In Meta Business Settings, assign the ad account to the system user that owns the token.</p>}
        <div role="radiogroup" aria-label="Ad accounts" className="space-y-2">
          {accounts.data?.accounts.map(a => (
            <label key={a.id} className={cn("flex cursor-pointer items-center gap-3 rounded-lg border px-3 py-2.5 text-sm transition-colors",
              picked === a.id ? "border-primary bg-primary/10" : "border-[var(--haip-border)] hover:bg-[var(--haip-surface)]")}>
              <input type="radio" name="ad-account" checked={picked === a.id} onChange={() => setPicked(a.id)} className="accent-primary" />
              <span className="min-w-0 flex-1"><span className="block truncate font-semibold text-[var(--haip-fg)]">{a.name || a.id}</span>
                <span className="block text-xs text-[var(--haip-fg-subtle)]">{a.id} · {a.currency}</span></span>
            </label>
          ))}
        </div>
        <button type="button" disabled={!picked || choose.isPending} onClick={() => choose.mutate(picked)}
          className="h-10 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground disabled:opacity-50">
          {choose.isPending ? "Saving…" : "Use this account"}
        </button>
      </CardBody>
    </Card>
  );
}

export default function MarketingPage() {
  const { data: session } = useSession();
  const role = session?.user?.role;
  const canChoose = role === "owner" || role === "manager";
  const qc = useQueryClient();
  const { toast } = useToast();
  const [days, setDays] = useState("30");

  const status = useQuery<AdsStatus>({
    queryKey: ["ads-status"], queryFn: () => api.get("/marketing/ads/status").then(r => r.data), staleTime: 30_000,
  });
  const summary = useQuery<Summary>({
    queryKey: ["ads-summary", days], enabled: !!status.data?.configured, staleTime: 60_000, placeholderData: p => p,
    queryFn: () => api.get("/marketing/ads/summary", { params: { days } }).then(r => r.data),
  });
  const sync = useMutation({
    mutationFn: () => api.post("/marketing/ads/sync").then(r => r.data),
    onSuccess: r => {
      qc.invalidateQueries({ queryKey: ["ads-status"] });
      qc.invalidateQueries({ queryKey: ["ads-summary"] });
      toast({ variant: "success", title: "Ads updated", description: `${r.created} new and ${r.updated} refreshed rows.` });
    },
    onError: e => toast({ variant: "error", title: "Could not update ads", description: errorText(e, "Try again in a few minutes.") }),
  });

  const s = status.data;
  const t = summary.data?.totals;
  const rows = summary.data?.campaigns ?? [];
  const range = RANGES.find(r => r.value === days)?.label.toLowerCase() ?? "";

  const columns: Column<Campaign>[] = [
    { key: "name", header: "Campaign", cell: c => (
      <div className="min-w-0">
        <p className="truncate font-semibold text-[var(--haip-fg)]">{c.campaign_name}</p>
        <p className="text-xs text-[var(--haip-fg-subtle)]">{c.ads > 0 ? `${c.ads} ad${c.ads === 1 ? "" : "s"}` : "Not in synced ads"}</p>
      </div>) },
    { key: "spend", header: "Spend", align: "right", cell: c => money(c.spend) },
    { key: "conv", header: "Chats started", align: "right", hideBelow: "sm", cell: c => num(c.meta_conversations) },
    { key: "leads", header: "Leads", align: "right", cell: c => num(c.haip_leads) },
    { key: "bookings", header: "Bookings", align: "right", hideBelow: "md", cell: c => num(c.bookings) },
    { key: "revenue", header: "Revenue", align: "right", hideBelow: "md", cell: c => money(c.revenue) },
    { key: "cpl", header: "Cost per lead", align: "right", hideBelow: "lg", cell: c => money(c.cost_per_lead) },
    { key: "roas", header: "Return", align: "right", cell: c => <span className="font-semibold">{roas(c.roas)}</span> },
  ];

  return (
    <div className="h-full overflow-y-auto bg-[var(--haip-bg,var(--background))]">
      <div className="mx-auto max-w-[1200px] space-y-5 px-4 py-5 sm:px-6">
        <PageHeader
          title="Marketing"
          subtitle={s?.ad_account
            ? `Meta ads · ${s.ad_account.name || s.ad_account.id} · updated ${ago(s.last_synced_at)}`
            : "What your Meta ads cost and what they bring in"}
          actions={s?.configured && (
            <>
              <Tabs label="Date range" value={days} onChange={setDays} items={RANGES} />
              <button type="button" onClick={() => sync.mutate()} disabled={sync.isPending}
                className="h-9 rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-3.5 text-[13px] font-semibold text-[var(--haip-fg-2)] hover:bg-[var(--haip-surface)] disabled:opacity-50">
                {sync.isPending ? "Updating…" : "Update now"}
              </button>
            </>
          )}
        />

        {status.isLoading ? (
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

            <section className="grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-6" aria-label="Totals">
              <Stat label="Spend" value={money(t?.spend)} hint={range} loading={!t} />
              <Stat label="Chats started" value={t ? num(t.meta_conversations) : "—"} hint="counted by Meta" loading={!t} />
              <Stat label="Leads in HAIP" value={t ? num(t.haip_leads) : "—"} hint="from these ads" loading={!t} />
              <Stat label="Bookings" value={t ? num(t.bookings) : "—"} hint="from those leads" loading={!t} />
              <Stat label="Revenue" value={money(t?.revenue)} hint="from those bookings" loading={!t} />
              <Stat label="Return on spend" value={roas(t?.roas)} hint={t?.roas == null ? "needs spend" : "revenue ÷ spend"} loading={!t} />
            </section>

            {t && t.attribution_gap > 0 && (
              <p className="rounded-lg border border-[var(--haip-border)] bg-[var(--haip-surface)] px-3 py-2 text-sm text-[var(--haip-fg-2)]">
                Meta counted {num(t.meta_conversations)} chats started, and HAIP traced {num(t.haip_conversations)} to an ad.{" "}
                {num(t.attribution_gap)} could not be linked, so leads and revenue here are a floor, not the full picture.
              </p>
            )}

            {summary.isError ? (
              <Card><EmptyState title="Could not load the summary" hint={errorText(summary.error, "Try again.")} /></Card>
            ) : t && rows.length === 0 ? (
              <Card><EmptyState title="No ad data yet" hint={`Nothing ran in the last ${days} days, or the first update has not finished. Use Update now.`} /></Card>
            ) : (
              <>
                {summary.data && summary.data.daily.length > 1 && (
                  <Card><CardHeader title="Daily spend" description={`Last ${days} days`} /><CardBody><SpendBars daily={summary.data.daily} /></CardBody></Card>
                )}
                <DataTable<Campaign> columns={columns} rows={rows} rowKey={c => c.campaign_id} loading={!summary.data}
                  empty={{ title: "No campaigns", hint: "Campaigns appear after the first update." }} maxHeightClass="max-h-none" />
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}
