"use client";
// Agency M5. Boost rules written as one sentence and approved once by the owner (an edit needs approving again);
// "Check now" shows what a rule would do today without creating anything. Insights: the funnel stage to fix and
// creative fatigue per ad (last 30 days), and the monthly keep / kill review by cost per booking.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { formatINR } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardBody, CardHeader, EmptyState, Stat, StatusPill, type Tone } from "@/components/ui/kit";
import { STUDIO, btn, btnPrimary, inputCls, studioError, when } from "./types";
import type { Rule } from "./AdsTab";

const ADS = `${STUDIO}/ads`;
type RuleBody = Pick<Rule, "condition" | "action"> & { name: string };
const NEW_RULE: RuleBody = {
  name: "Fill quiet weekends",
  condition: { window: "weekend", days_ahead: 10, occupancy_below_pct: 50 },
  action: { content: "latest_reel", content_id: null, daily_budget_inr: 1000, days: 3, max_total_inr: 3000 },
};

function sentence(r: RuleBody): string {
  const what = r.action.content === "latest_reel" ? "the latest approved reel" : r.action.content === "latest_post" ? "the latest approved post" : "the chosen post";
  return `If a ${r.condition.window === "weekend" ? "weekend" : "long weekend"} is under ${r.condition.occupancy_below_pct}% booked ` +
    `${r.condition.days_ahead} days out, boost ${what} at ${formatINR(r.action.daily_budget_inr)}/day for up to ${r.action.days} days, ` +
    `never more than ${formatINR(r.action.max_total_inr)}.`;
}

function Num({ label, value, onChange, min, max, step = 1 }: { label: string; value: number; onChange: (n: number) => void; min: number; max: number; step?: number }) {
  return (
    <label className="space-y-1"><span className="text-[13px] font-semibold text-[var(--haip-fg-2)]">{label}</span>
      <input className={inputCls} type="number" inputMode="numeric" min={min} max={max} step={step} value={value} onChange={e => onChange(Number(e.target.value) || 0)} /></label>
  );
}

function RuleForm({ initial, onSave, busy, onCancel }: { initial: RuleBody; onSave: (r: RuleBody) => void; busy: boolean; onCancel: () => void }) {
  const [r, setR] = useState(initial);
  const c = (k: keyof RuleBody["condition"], v: unknown) => setR({ ...r, condition: { ...r.condition, [k]: v } });
  const a = (k: keyof RuleBody["action"], v: unknown) => setR({ ...r, action: { ...r.action, [k]: v } });
  return (
    <form className="space-y-3 rounded-xl border border-[var(--haip-border)] p-3" onSubmit={e => { e.preventDefault(); onSave(r); }}>
      <label className="block space-y-1"><span className="text-[13px] font-semibold text-[var(--haip-fg-2)]">Name</span>
        <input className={inputCls} maxLength={80} value={r.name} onChange={e => setR({ ...r, name: e.target.value })} /></label>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        <label className="space-y-1"><span className="text-[13px] font-semibold text-[var(--haip-fg-2)]">When</span>
          <select className={inputCls} value={r.condition.window} onChange={e => c("window", e.target.value)}>
            <option value="weekend">A weekend</option><option value="long_weekend">A long weekend</option></select></label>
        <Num label="is under (% booked)" value={r.condition.occupancy_below_pct} min={1} max={100} onChange={v => c("occupancy_below_pct", v)} />
        <Num label="days out" value={r.condition.days_ahead} min={2} max={60} onChange={v => c("days_ahead", v)} />
        <label className="space-y-1"><span className="text-[13px] font-semibold text-[var(--haip-fg-2)]">Boost</span>
          <select className={inputCls} value={r.action.content} onChange={e => a("content", e.target.value)}>
            <option value="latest_reel">Latest approved reel</option><option value="latest_post">Latest approved post</option></select></label>
        <Num label="₹ per day" value={r.action.daily_budget_inr} min={100} max={100000} step={100} onChange={v => a("daily_budget_inr", v)} />
        <Num label="for up to (days)" value={r.action.days} min={1} max={14} onChange={v => a("days", v)} />
        <Num label="never more than (₹)" value={r.action.max_total_inr} min={100} max={1000000} step={100} onChange={v => a("max_total_inr", v)} />
      </div>
      <p className="text-sm text-[var(--haip-fg-2)]">{sentence(r)}</p>
      <div className="flex gap-2">
        <button type="submit" className={btnPrimary} disabled={busy || r.action.max_total_inr < r.action.daily_budget_inr}>Save rule</button>
        <button type="button" className={btn} onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}

export function BoostRules({ rules, isOwner, canApprove }: { rules: Rule[]; isOwner: boolean; canApprove: boolean }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [editing, setEditing] = useState<string | "new" | null>(null);
  const [checked, setChecked] = useState<Record<string, string>>({});
  const done = (title: string) => () => { setEditing(null); qc.invalidateQueries({ queryKey: ["studio-ads"] }); toast({ variant: "success", title }); };
  const fail = (e: unknown) => toast({ variant: "error", title: "Not done", description: studioError(e, "Try again.") });
  const save = useMutation({
    mutationFn: ({ id, body }: { id?: string; body: RuleBody }) => id ? api.put(`${ADS}/rules/${id}`, body) : api.post(`${ADS}/rules`, body),
    onSuccess: done("Rule saved: the owner approves it before it runs"), onError: fail,
  });
  const act = useMutation({
    mutationFn: ({ id, a }: { id: string; a: "approve" | "pause" }) => api.post(`${ADS}/rules/${id}/${a}`),
    onSuccess: (_, v) => done(v.a === "approve" ? "Rule approved: it checks every hour" : "Rule paused")(), onError: fail,
  });
  const check = useMutation({
    mutationFn: (id: string) => api.post(`${ADS}/rules/${id}/check`).then(r => ({ id, d: r.data })),
    onSuccess: ({ id, d }) => setChecked({ ...checked, [id]: d.action === "would_boost"
      ? `Today it would boost “${d.content}” for the ${d.window} (${d.booked_pct}% booked).` : (d.reason ?? "Nothing to do today.") }),
    onError: fail,
  });
  return (
    <Card>
      <CardHeader title="Boost rules" description="Approved once by the owner, then checked every hour against your own calendar." />
      <CardBody className="space-y-3">
        {!rules.length && editing !== "new" && <EmptyState title="No boost rules" hint="A rule boosts a post when a weekend is filling slowly." />}
        <ul className="space-y-3">
          {rules.map(r => editing === r.id ? (
            <li key={r.id}><RuleForm initial={r} busy={save.isPending} onCancel={() => setEditing(null)} onSave={body => save.mutate({ id: r.id, body })} /></li>
          ) : (
            <li key={r.id} className="space-y-2 rounded-xl border border-[var(--haip-border)] p-3">
              <p className="flex flex-wrap items-center gap-2 text-sm font-semibold text-[var(--haip-fg)]">
                {r.name}
                <StatusPill tone={r.in_force ? "success" : r.status === "paused" ? "neutral" : "warning"}>{r.in_force ? "In force" : r.status === "paused" ? "Paused" : "Needs the owner's approval"}</StatusPill>
              </p>
              <p className="text-sm text-[var(--haip-fg-2)]">{sentence(r)}</p>
              {r.last_checked_at && r.last_result && (
                <p className="text-xs text-[var(--haip-fg-subtle)]">Checked {when(r.last_checked_at)}: {r.last_result.action === "boosted" ? `boosted the ${r.last_result.window}` : r.last_result.reason ?? r.last_result.action}</p>
              )}
              {checked[r.id] && <p className="text-xs text-[var(--haip-fg-2)]">{checked[r.id]}</p>}
              <div className="flex flex-wrap gap-2">
                {isOwner && !r.in_force && <button type="button" className={btnPrimary} disabled={act.isPending} onClick={() => act.mutate({ id: r.id, a: "approve" })}>Approve rule</button>}
                {canApprove && r.in_force && <button type="button" className={btn} disabled={act.isPending} onClick={() => act.mutate({ id: r.id, a: "pause" })}>Pause</button>}
                <button type="button" className={btn} disabled={check.isPending} onClick={() => check.mutate(r.id)}>Check now</button>
                <button type="button" className={btn} onClick={() => setEditing(r.id)}>Edit</button>
              </div>
            </li>
          ))}
        </ul>
        {editing === "new" ? <RuleForm initial={NEW_RULE} busy={save.isPending} onCancel={() => setEditing(null)} onSave={body => save.mutate({ body })} />
          : <button type="button" className={btn} onClick={() => setEditing("new")}>New boost rule</button>}
      </CardBody>
    </Card>
  );
}

interface InsightAd { ad_id: string; name: string; spend: number; impressions: number; conversations: number; bookings: number; stage: string | null; advice: string; fatigue: { advice: string } | null }
interface ReviewAd { ad_id: string; name: string; spend: number; bookings: number; revenue: number; cost_per_booking: number | null; roas: number | null; verdict: "keep" | "kill" | "test_more"; why: string }
interface Review { month: string; totals: { spend: number; bookings: number; revenue: number; cost_per_booking: number | null; roas: number | null; meta_conversations: number; haip_leads: number }; ads: ReviewAd[] }
const STAGE: Record<string, string> = { hook: "Fix the first 3 seconds", click: "Fix the offer", chat: "Fix the message button", booking: "Fix the follow-up" };
const VERDICT: Record<ReviewAd["verdict"], { label: string; tone: Tone }> = { keep: { label: "Keep", tone: "success" }, kill: { label: "Stop", tone: "danger" }, test_more: { label: "Test more", tone: "neutral" } };

function lastMonth(): string {
  const d = new Date();
  d.setDate(1);
  d.setMonth(d.getMonth() - 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export function AdsInsights() {
  const [month, setMonth] = useState(lastMonth);
  const ins = useQuery<{ since: string; until: string; ads: InsightAd[] }>({ queryKey: ["studio-ads-insights"], queryFn: () => api.get(`${ADS}/insights`).then(r => r.data) });
  const rev = useQuery<Review>({ queryKey: ["studio-ads-review", month], queryFn: () => api.get(`${ADS}/review`, { params: { month } }).then(r => r.data) });
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader title="What to fix" description={ins.data ? `Each ad against your own ads, ${ins.data.since} to ${ins.data.until}` : "Last 30 days"} />
        <CardBody>
          {ins.isLoading ? <Skeleton className="h-32 w-full" /> : ins.isError ? <p className="text-sm text-[var(--haip-status-danger-fg)]">{studioError(ins.error, "Could not load.")}</p>
            : !ins.data?.ads.length ? <EmptyState title="No ad data yet" hint="It fills in after the daily Meta sync." /> : (
              <ul className="divide-y divide-[var(--haip-border)]">
                {ins.data.ads.map(a => (
                  <li key={a.ad_id} className="space-y-1 py-2.5">
                    <p className="flex flex-wrap items-center gap-2 text-sm font-semibold text-[var(--haip-fg)]">
                      <span className="[overflow-wrap:anywhere]">{a.name}</span>
                      {a.stage && <StatusPill tone="warning">{STAGE[a.stage]}</StatusPill>}
                      {a.fatigue && <StatusPill tone="highlight">Tired creative</StatusPill>}
                    </p>
                    <p className="text-xs text-[var(--haip-fg-subtle)] tabular-nums">{formatINR(a.spend)} · {a.conversations} chats · {a.bookings} bookings</p>
                    <p className="text-xs text-[var(--haip-fg-2)]">{a.fatigue?.advice ?? a.advice}</p>
                  </li>
                ))}
              </ul>
            )}
        </CardBody>
      </Card>
      <Card>
        <CardHeader title="Monthly review" description="Keep, stop or test more, by cost per booking against your own ads." />
        <CardBody className="space-y-3">
          <input type="month" aria-label="Month" className={inputCls + " sm:max-w-[12rem]"} value={month} onChange={e => e.target.value && setMonth(e.target.value)} />
          {rev.isLoading ? <Skeleton className="h-32 w-full" /> : rev.isError || !rev.data ? <p className="text-sm text-[var(--haip-status-danger-fg)]">{studioError(rev.error, "Could not load.")}</p> : (
            <>
              <div className="grid grid-cols-2 gap-3">
                <Stat label="Cost per booking" value={rev.data.totals.cost_per_booking != null ? formatINR(rev.data.totals.cost_per_booking) : rev.data.totals.spend ? "No bookings" : "—"} hint={`${rev.data.month}: ${formatINR(rev.data.totals.spend)} for ${rev.data.totals.bookings} bookings`} />
                <Stat label="Revenue per ₹1" value={rev.data.totals.roas != null ? `₹${rev.data.totals.roas}` : "—"} hint={`Meta: ${rev.data.totals.meta_conversations} chats · HAIP traced ${rev.data.totals.haip_leads} leads`} />
              </div>
              {!rev.data.ads.length ? <EmptyState title="No ad spend that month" hint="Pick another month." /> : (
                <ul className="divide-y divide-[var(--haip-border)]">
                  {rev.data.ads.map(a => (
                    <li key={a.ad_id} className="space-y-1 py-2.5">
                      <p className="flex flex-wrap items-center gap-2 text-sm font-semibold text-[var(--haip-fg)]">
                        <span className="[overflow-wrap:anywhere]">{a.name}</span><StatusPill tone={VERDICT[a.verdict].tone}>{VERDICT[a.verdict].label}</StatusPill>
                      </p>
                      <p className="text-xs text-[var(--haip-fg-subtle)] tabular-nums">{formatINR(a.spend)} · {a.bookings} bookings{a.cost_per_booking != null ? ` · ${formatINR(a.cost_per_booking)} each` : ""}</p>
                      <p className="text-xs text-[var(--haip-fg-2)]">{a.why}</p>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
