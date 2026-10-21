"use client";
// Agency M5, performance marketer (GET /marketing/studio/ads). Nothing is spent until the owner sets a monthly budget,
// the performance marketer is on (Agency tab) and a person approves the ad, or an owner-approved boost rule made it.
// Every amount says what it covers; money in rupees, Indian grouping.
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import api from "@/lib/api";
import { formatINR } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardBody, CardHeader, EmptyState, Stat, StatusPill, type Tone } from "@/components/ui/kit";
import { STUDIO, btn, btnPrimary, inputCls, studioError, when } from "./types";
import { AdsInsights, BoostRules } from "./AdsRules";

const ADS = `${STUDIO}/ads`;

export interface Audience { label: string; latitude: number; longitude: number; radius_km: number; age_min: number; age_max: number }
interface Settings { monthly_cap_inr: number; destination: "whatsapp" | "instagram"; audience: Audience | null; capi_enabled: boolean; dataset_id: string | null; capi_test_code: string | null }
export interface AdDraft {
  id: string; content_id: string; content_title: string | null; origin: "manual" | "rule"; window_key: string | null;
  destination: string; daily_budget_inr: number; days: number; spend_cap_inr: number; status: string;
  approved_at: string | null; approval_note: string | null; starts_at: string | null; ends_at: string | null;
  spent_inr: number | null; error: string | null; created_at: string; created_by: string | null;
}
export interface Rule {
  id: string; name: string; status: string; in_force: boolean; last_checked_at: string | null;
  condition: { window: "weekend" | "long_weekend"; days_ahead: number; occupancy_below_pct: number };
  action: { content: "latest_reel" | "latest_post" | "specific"; content_id: string | null; daily_budget_inr: number; days: number; max_total_inr: number };
  last_result: { action: string; reason?: string; window?: string; booked_pct?: number } | null;
}
export interface Overview { settings: Settings; committed_inr: number; budget_left_inr: number; ads_level: string; paused: boolean; drafts: AdDraft[]; rules: Rule[] }

const STATUS: Record<string, { label: string; tone: Tone }> = {
  draft: { label: "Waiting for approval", tone: "warning" }, approved: { label: "Starting", tone: "info" },
  pushing: { label: "Starting", tone: "info" }, live: { label: "Running", tone: "success" },
  paused: { label: "Paused", tone: "neutral" }, ended: { label: "Finished", tone: "neutral" },
  failed: { label: "Did not start", tone: "danger" }, cancelled: { label: "Cancelled", tone: "neutral" },
};

export function useAds() {
  return useQuery<Overview>({ queryKey: ["studio-ads"], queryFn: () => api.get(ADS).then(r => r.data) });
}

export function AdsTab() {
  const { data: session } = useSession();
  const role = session?.user?.role;
  const canApprove = role === "owner" || role === "manager";
  const q = useAds();
  if (q.isLoading) return <Skeleton className="h-64 w-full" />;
  if (q.isError || !q.data) return <Card><EmptyState title="Could not load ads" hint={studioError(q.error, "Try again.")} /></Card>;
  const o = q.data;
  const cap = o.settings.monthly_cap_inr;
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <Stat label="Left to spend" value={cap ? formatINR(o.budget_left_inr) : "Nothing"} hint={cap ? `of ${formatINR(cap)} this month` : "No monthly budget set"} />
        <Stat label="Committed" value={formatINR(o.committed_inr)} hint="this month: running caps + money spent" />
        <Stat label="Performance marketer" value={o.paused ? "Paused" : o.ads_level === "autopilot" ? "Autopilot" : o.ads_level === "suggest" ? "Suggests" : "Off"}
          hint={o.ads_level === "off" ? "Switch it on in the Agency tab" : o.ads_level === "autopilot" ? "Approved boost rules run alone" : "A person approves every ad"} />
      </div>
      {!cap && (
        <p className="rounded-lg bg-[var(--haip-status-warning-bg)] p-3 text-sm text-[var(--haip-status-warning-fg)]">
          HAIP will not spend anything until the owner sets a monthly ads budget below.
        </p>
      )}
      <AdList drafts={o.drafts} canApprove={canApprove} />
      <BoostRules rules={o.rules} isOwner={role === "owner"} canApprove={canApprove} />
      {canApprove && <AdsInsights />}
      <AdsSettings settings={o.settings} isOwner={role === "owner"} />
    </div>
  );
}

function AdList({ drafts, canApprove }: { drafts: AdDraft[]; canApprove: boolean }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const act = useMutation({
    mutationFn: ({ id, a }: { id: string; a: "approve" | "cancel" | "pause" }) => api.post(`${ADS}/drafts/${id}/${a}`, {}),
    onSuccess: (_, v) => { qc.invalidateQueries({ queryKey: ["studio-ads"] }); toast({ variant: "success", title: v.a === "approve" ? "Approved: starting on Meta" : v.a === "pause" ? "Paused" : "Cancelled" }); },
    onError: e => toast({ variant: "error", title: "Not done", description: studioError(e, "Try again.") }),
  });
  return (
    <Card>
      <CardHeader title="Ads" description="Each ad shows one approved post. Its cap is also set on Meta, so Meta stops it there too." />
      <CardBody>
        {!drafts.length ? <EmptyState title="No ads yet" hint="Open an approved post in Content and choose “Promote as an ad”." /> : (
          <ul className="divide-y divide-[var(--haip-border)]">
            {drafts.map(d => {
              const s = STATUS[d.status] ?? { label: d.status, tone: "neutral" as Tone };
              return (
                <li key={d.id} className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0 space-y-1">
                    <p className="flex flex-wrap items-center gap-2 text-sm font-semibold text-[var(--haip-fg)]">
                      <span className="[overflow-wrap:anywhere]">{d.content_title ?? "Post"}</span>
                      <StatusPill tone={s.tone}>{s.label}</StatusPill>
                      {d.origin === "rule" && <StatusPill tone="brand">Boost rule</StatusPill>}
                    </p>
                    <p className="text-xs text-[var(--haip-fg-subtle)] tabular-nums">
                      {formatINR(d.daily_budget_inr)}/day · {d.days} {d.days === 1 ? "day" : "days"} · cap {formatINR(d.spend_cap_inr)}
                      {d.spent_inr != null ? ` · spent ${formatINR(d.spent_inr)}` : ""} · {d.destination === "whatsapp" ? "WhatsApp chats" : "Instagram DMs"}
                      {d.starts_at ? ` · ${when(d.starts_at)} to ${when(d.ends_at)}` : ""}
                    </p>
                    {d.approval_note && <p className="text-xs text-[var(--haip-fg-subtle)]">{d.approval_note}</p>}
                    {d.error && <p className="text-xs text-[var(--haip-status-danger-fg)]">{d.error}</p>}
                  </div>
                  {canApprove && (
                    <div className="flex shrink-0 gap-2">
                      {d.status === "draft" && <button type="button" className={btnPrimary} disabled={act.isPending} onClick={() => act.mutate({ id: d.id, a: "approve" })}>Approve spend</button>}
                      {["draft", "approved", "failed"].includes(d.status) && <button type="button" className={btn} disabled={act.isPending} onClick={() => act.mutate({ id: d.id, a: "cancel" })}>Cancel</button>}
                      {d.status === "live" && <button type="button" className={btn} disabled={act.isPending} onClick={() => act.mutate({ id: d.id, a: "pause" })}>Pause</button>}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </CardBody>
    </Card>
  );
}

function AdsSettings({ settings, isOwner }: { settings: Settings; isOwner: boolean }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [s, setS] = useState(settings);
  useEffect(() => setS(settings), [settings]);
  const save = useMutation({
    mutationFn: () => api.put(`${ADS}/settings`, s),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["studio-ads"] }); toast({ variant: "success", title: "Ads settings saved" }); },
    onError: e => toast({ variant: "error", title: "Not saved", description: studioError(e, "Check the fields.") }),
  });
  const a = s.audience ?? { label: "", latitude: 12.9716, longitude: 77.5946, radius_km: 40, age_min: 25, age_max: 55 };
  const setA = (k: keyof Audience, v: string) => setS({ ...s, audience: { ...a, [k]: k === "label" ? v : Number(v) } });
  const num = (label: string, k: keyof Audience, step = "1") => (
    <label className="space-y-1"><span className="text-[13px] font-semibold text-[var(--haip-fg-2)]">{label}</span>
      <input className={inputCls} type="number" inputMode="decimal" step={step} value={String(a[k])} onChange={e => setA(k, e.target.value)} /></label>
  );
  return (
    <Card>
      <CardHeader title="Ads settings" description={isOwner ? "Only you can change the money limits and what is shared with Meta." : "Set by the owner."} />
      <CardBody>
        <form className="grid gap-4 md:grid-cols-2" onSubmit={e => { e.preventDefault(); save.mutate(); }}>
          <fieldset disabled={!isOwner || save.isPending} className="contents">
            <label className="space-y-1"><span className="text-[13px] font-semibold text-[var(--haip-fg-2)]">Monthly ads budget (₹)</span>
              <input className={inputCls} type="number" inputMode="numeric" min={0} step={500} value={s.monthly_cap_inr}
                onChange={e => setS({ ...s, monthly_cap_inr: Math.max(0, Number(e.target.value) || 0) })} />
              <span className="block text-xs text-[var(--haip-fg-subtle)]">0 = HAIP never spends. The total of every ad's cap this month stays under it.</span></label>
            <label className="space-y-1"><span className="text-[13px] font-semibold text-[var(--haip-fg-2)]">Ads open a chat on</span>
              <select className={inputCls} value={s.destination} onChange={e => setS({ ...s, destination: e.target.value as Settings["destination"] })}>
                <option value="whatsapp">WhatsApp</option><option value="instagram">Instagram DM</option>
              </select></label>
            <label className="space-y-1 md:col-span-2"><span className="text-[13px] font-semibold text-[var(--haip-fg-2)]">Who sees the ads: place name</span>
              <input className={inputCls} maxLength={80} placeholder="e.g. Bengaluru" value={a.label} onChange={e => setA("label", e.target.value)} /></label>
            <div className="grid grid-cols-2 gap-3 md:col-span-2 md:grid-cols-5">
              {num("Latitude", "latitude", "0.0001")}{num("Longitude", "longitude", "0.0001")}{num("Radius (km)", "radius_km")}
              {num("Youngest", "age_min")}{num("Oldest", "age_max")}
            </div>
            <label className="flex min-h-11 items-center gap-2 text-sm text-[var(--haip-fg-2)] md:col-span-2">
              <input type="checkbox" className="size-4" checked={s.capi_enabled} onChange={e => setS({ ...s, capi_enabled: e.target.checked })} />
              Tell Meta about bookings (Conversions API): only guests who agreed to marketing, only scrambled phone and email
            </label>
            {s.capi_enabled && (
              <>
                <label className="space-y-1"><span className="text-[13px] font-semibold text-[var(--haip-fg-2)]">Meta dataset (pixel) id</span>
                  <input className={inputCls} inputMode="numeric" value={s.dataset_id ?? ""} onChange={e => setS({ ...s, dataset_id: e.target.value.trim() || null })} /></label>
                <label className="space-y-1"><span className="text-[13px] font-semibold text-[var(--haip-fg-2)]">Test events code (optional)</span>
                  <input className={inputCls} value={s.capi_test_code ?? ""} onChange={e => setS({ ...s, capi_test_code: e.target.value.trim() || null })} />
                  <span className="block text-xs text-[var(--haip-fg-subtle)]">While set, Meta shows the events under Test events and does not use them.</span></label>
              </>
            )}
          </fieldset>
          {isOwner && <div className="md:col-span-2"><button type="submit" className={btnPrimary} disabled={save.isPending}>{save.isPending ? "Saving…" : "Save ads settings"}</button></div>}
        </form>
      </CardBody>
    </Card>
  );
}

/** In the content drawer: turn an approved post into an ad draft (nothing is spent until it is approved). */
export function PromoteButton({ contentId }: { contentId: string }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [daily, setDaily] = useState(500);
  const [days, setDays] = useState(3);
  const make = useMutation({
    mutationFn: () => api.post(`${ADS}/drafts`, { content_id: contentId, daily_budget_inr: daily, days }),
    onSuccess: () => { setOpen(false); qc.invalidateQueries({ queryKey: ["studio-ads"] }); toast({ variant: "success", title: "Ad drafted", description: "Approve the spend in the Ads tab." }); },
    onError: e => toast({ variant: "error", title: "Not drafted", description: studioError(e, "Check the budget.") }),
  });
  if (!open) return <button type="button" className={btn} onClick={() => setOpen(true)}>Promote as an ad</button>;
  return (
    <form className="grid gap-2 rounded-xl border border-[var(--haip-border)] p-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end" onSubmit={e => { e.preventDefault(); make.mutate(); }}>
      <label className="space-y-1"><span className="text-[13px] font-semibold text-[var(--haip-fg-2)]">₹ per day</span>
        <input className={inputCls} type="number" inputMode="numeric" min={100} step={100} value={daily} onChange={e => setDaily(Number(e.target.value) || 0)} /></label>
      <label className="space-y-1"><span className="text-[13px] font-semibold text-[var(--haip-fg-2)]">Days</span>
        <input className={inputCls} type="number" inputMode="numeric" min={1} max={30} value={days} onChange={e => setDays(Number(e.target.value) || 0)} /></label>
      <span className="flex gap-2">
        <button type="submit" className={btnPrimary} disabled={make.isPending || daily < 100 || days < 1}>Draft · cap {formatINR(daily * days)}</button>
        <button type="button" className={btn} onClick={() => setOpen(false)}>Cancel</button>
      </span>
    </form>
  );
}
