"use client";
// Agency M6, Results (GET /marketing/studio/results/*). Bookings are the one source of truth: each one names the post
// or ad behind it when the chain is known, and the report says how many it cannot trace. Money and revenue are shown
// to owners and managers only; the health score and what-works learning to everyone in Marketing Studio.
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import api from "@/lib/api";
import { formatINR } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardBody, CardHeader, EmptyState, Stat, StatusPill, type Tone } from "@/components/ui/kit";
import { STUDIO, btnPrimary, inputCls, studioError } from "./types";

const RES = `${STUDIO}/results`;

interface Health { score: number; as_of: string; parts: { key: string; score: number; detail: string }[] }
interface Touch { kind: string; channel: string | null; detail: string | null }
interface BookingRow { stay_id: string; amount: number; check_in: string; property: string | null; credited_title: string | null; heard_about: string | null; chain: { known: boolean; first: Touch | null } }
interface Week { since: string; until: string; bookings: number; revenue: number; traced: number; unknown: number; unknown_share: number | null; ad_spend: number; cost_per_traced_booking: number | null; meta_chats: number; haip_traced_chats: number; posts_published: number; booking_rows: BookingRow[] }
interface Metric { key: string; label: string; this: number | null; last: number | null; target: number | null; status: "on_track" | "at_risk" | "off_track" | null }
interface Monthly { month: string; elapsed: number; metrics: Metric[]; meta_vs_haip: { meta_chats: number; haip_traced_chats: number } }
interface Value { value: string; posts: number; wins: number; win_rate: number; p_best: number | null; enough: boolean }
interface Learning { posts: number; note: string | null; elements: Record<string, Value[]> }
interface Split { note: string | null; ads: { ad_id: string; name: string | null; chats: number; clicks: number; share: number }[] }

const STATUS: Record<string, { label: string; tone: Tone }> = { on_track: { label: "On track", tone: "success" }, at_risk: { label: "At risk", tone: "warning" }, off_track: { label: "Off track", tone: "danger" } };
const PART: Record<string, string> = { cadence: "Posting", engagement: "Engagement", traceability: "Traceability", approvals: "Approvals" };
const ELEMENT: Record<string, string> = { format: "Format", hook: "First line", shot: "Main photo", pillar: "Theme" };
const MONEY = new Set(["revenue", "ad_spend", "cost_per_traced_booking"]);

function money(key: string, v: number | null) {
  if (v == null) return "—";
  return MONEY.has(key) ? formatINR(v) : String(v);
}

export function ResultsTab() {
  const { data: session } = useSession();
  const role = session?.user?.role;
  const approver = role === "owner" || role === "manager";
  return (
    <div className="space-y-4">
      <HealthCard />
      {approver && <WeeklyCard />}
      {approver && <MonthlyCard />}
      <LearningCard />
      {approver && <SplitCard />}
      <ReportSettings isOwner={role === "owner"} />
    </div>
  );
}

function HealthCard() {
  const q = useQuery<Health>({ queryKey: ["studio-health"], queryFn: () => api.get(`${RES}/health`).then(r => r.data) });
  return (
    <Card>
      <CardHeader title="Marketing health" description={q.data ? `Last 28 days, as of ${q.data.as_of}` : "Last 28 days"} />
      <CardBody>
        {q.isLoading ? <Skeleton className="h-24 w-full" /> : q.isError || !q.data ? <p className="text-sm text-[var(--haip-status-danger-fg)]">{studioError(q.error, "Could not load.")}</p> : (
          <div className="grid gap-4 sm:grid-cols-[auto_1fr] sm:items-center">
            <p className="font-[family-name:var(--font-display)] text-[44px] font-semibold leading-none tabular-nums text-[var(--haip-fg)]">{q.data.score}<span className="text-[18px] text-[var(--haip-fg-subtle)]">/100</span></p>
            <ul className="grid gap-1.5 sm:grid-cols-2">
              {q.data.parts.map(p => (
                <li key={p.key} className="text-sm"><span className="font-semibold text-[var(--haip-fg)] tabular-nums">{PART[p.key] ?? p.key} {Math.round(p.score)}/25</span>
                  <span className="block text-xs text-[var(--haip-fg-subtle)]">{p.detail}</span></li>
              ))}
            </ul>
          </div>
        )}
      </CardBody>
    </Card>
  );
}

function WeeklyCard() {
  const q = useQuery<{ week: Week }>({ queryKey: ["studio-weekly"], queryFn: () => api.get(`${RES}/weekly`).then(r => r.data) });
  const w = q.data?.week;
  return (
    <Card>
      <CardHeader title="Last week" description={w ? `${w.since} to ${w.until}: the post or ad behind each booking` : "The post or ad behind each booking"} />
      <CardBody className="space-y-3">
        {q.isLoading ? <Skeleton className="h-32 w-full" /> : q.isError || !w ? <p className="text-sm text-[var(--haip-status-danger-fg)]">{studioError(q.error, "Could not load.")}</p> : (
          <>
            <div className="grid gap-3 sm:grid-cols-3">
              <Stat label="Bookings" value={w.bookings} hint={`${formatINR(w.revenue)} booked`} />
              <Stat label="Traced to a post or ad" value={`${w.traced} of ${w.bookings}`} hint={w.unknown ? `${w.unknown} unknown` : "none unknown"} />
              <Stat label="Ad spend" value={formatINR(w.ad_spend)} hint={w.cost_per_traced_booking != null ? `${formatINR(w.cost_per_traced_booking)} per traced booking` : `Meta: ${w.meta_chats} chats · HAIP traced ${w.haip_traced_chats}`} />
            </div>
            {!w.booking_rows.length ? <EmptyState title="No bookings last week" hint="Each booking will show the post or ad behind it here." /> : (
              <ul className="divide-y divide-[var(--haip-border)]">
                {w.booking_rows.map(r => (
                  <li key={r.stay_id} className="flex flex-col gap-1 py-2.5 sm:flex-row sm:items-center sm:justify-between">
                    <span className="min-w-0 text-sm">
                      <span className="font-semibold text-[var(--haip-fg)] tabular-nums">{formatINR(r.amount)}</span>
                      <span className="text-[var(--haip-fg-subtle)]"> · {r.property ?? "Stay"} · from {r.check_in}</span>
                      {r.heard_about && <span className="block text-xs text-[var(--haip-fg-subtle)]">Guest said: {r.heard_about}</span>}
                    </span>
                    {r.credited_title ? <StatusPill tone="brand">{r.credited_title}</StatusPill>
                      : <StatusPill tone="neutral">Unknown{r.chain.first?.channel ? ` · first contact ${r.chain.first.channel}` : ""}</StatusPill>}
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </CardBody>
    </Card>
  );
}

function thisMonth() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function MonthlyCard() {
  const [month, setMonth] = useState(thisMonth);
  const q = useQuery<Monthly>({ queryKey: ["studio-monthly", month], queryFn: () => api.get(`${RES}/monthly`, { params: { month } }).then(r => r.data) });
  return (
    <Card>
      <CardHeader title="Month" description={q.data ? `This month vs last month vs target${q.data.elapsed < 1 ? ` (${Math.round(q.data.elapsed * 100)}% of the month gone)` : ""}` : "This month vs last month vs target"} />
      <CardBody className="space-y-3">
        <input type="month" aria-label="Month" className={inputCls + " sm:max-w-[12rem]"} value={month} onChange={e => e.target.value && setMonth(e.target.value)} />
        {q.isLoading ? <Skeleton className="h-32 w-full" /> : q.isError || !q.data ? <p className="text-sm text-[var(--haip-status-danger-fg)]">{studioError(q.error, "Could not load.")}</p> : (
          <>
            <ul className="divide-y divide-[var(--haip-border)]">
              {q.data.metrics.map(m => (
                <li key={m.key} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2 py-2.5">
                  <span className="min-w-0 text-sm">
                    <span className="font-semibold text-[var(--haip-fg)]">{m.label}</span>
                    <span className="block text-xs text-[var(--haip-fg-subtle)] tabular-nums">
                      {money(m.key, m.this)} this month · {money(m.key, m.last)} last month{m.target != null ? ` · target ${money(m.key, m.target)}` : ""}
                    </span>
                  </span>
                  {m.status ? <StatusPill tone={STATUS[m.status].tone}>{STATUS[m.status].label}</StatusPill> : <span className="text-xs text-[var(--haip-fg-subtle)]">No target</span>}
                </li>
              ))}
            </ul>
            <p className="text-xs text-[var(--haip-fg-subtle)]">Meta says {q.data.meta_vs_haip.meta_chats} chats started this month; HAIP traced {q.data.meta_vs_haip.haip_traced_chats}.</p>
          </>
        )}
      </CardBody>
    </Card>
  );
}

function LearningCard() {
  const q = useQuery<Learning>({ queryKey: ["studio-learning"], queryFn: () => api.get(`${RES}/learning`).then(r => r.data) });
  return (
    <Card>
      <CardHeader title="What works" description="Published posts against your own median engagement. The plan leans on what wins." />
      <CardBody>
        {q.isLoading ? <Skeleton className="h-32 w-full" /> : q.isError || !q.data ? <p className="text-sm text-[var(--haip-status-danger-fg)]">{studioError(q.error, "Could not load.")}</p>
          : q.data.note ? <EmptyState title="Not enough signal yet" hint={q.data.note} /> : (
            <div className="grid gap-4 md:grid-cols-2">
              {Object.entries(q.data.elements).map(([el, values]) => (
                <div key={el} className="space-y-1.5">
                  <h4 className="text-[13px] font-bold text-[var(--haip-fg)]">{ELEMENT[el] ?? el}</h4>
                  <ul className="space-y-1">
                    {values.slice(0, 4).map(v => (
                      <li key={v.value} className="flex items-center justify-between gap-2 text-sm">
                        <span className="min-w-0 [overflow-wrap:anywhere] text-[var(--haip-fg-2)]">{v.value.replace(/_/g, " ")}</span>
                        <span className="shrink-0 text-xs tabular-nums text-[var(--haip-fg-subtle)]">
                          beat the median {v.wins} of {v.posts}{v.p_best != null ? ` · ${Math.round(v.p_best * 100)}% chance best` : v.enough ? "" : " · too few"}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          )}
      </CardBody>
    </Card>
  );
}

function SplitCard() {
  const q = useQuery<Split>({ queryKey: ["studio-ads-split"], queryFn: () => api.get(`${RES}/ads-split`).then(r => r.data) });
  return (
    <Card>
      <CardHeader title="Where the next ads money should go" description="A suggestion from the last 14 days' chats per click; nothing changes on Meta." />
      <CardBody>
        {q.isLoading ? <Skeleton className="h-20 w-full" /> : q.isError || !q.data ? <p className="text-sm text-[var(--haip-status-danger-fg)]">{studioError(q.error, "Could not load.")}</p>
          : q.data.note ? <p className="text-sm text-[var(--haip-fg-subtle)]">{q.data.note}</p> : (
            <ul className="space-y-2">
              {q.data.ads.map(a => (
                <li key={a.ad_id} className="space-y-1">
                  <p className="flex justify-between gap-2 text-sm"><span className="min-w-0 [overflow-wrap:anywhere] text-[var(--haip-fg)]">{a.name ?? a.ad_id}</span>
                    <span className="shrink-0 font-semibold tabular-nums">{Math.round(a.share * 100)}%</span></p>
                  <progress value={Math.round(a.share * 100)} max={100} aria-label={`${a.name ?? a.ad_id} share`}
                    className="h-2 w-full overflow-hidden rounded-full [&::-moz-progress-bar]:bg-primary [&::-webkit-progress-bar]:bg-[var(--haip-surface)] [&::-webkit-progress-value]:bg-primary" />
                  <p className="text-xs text-[var(--haip-fg-subtle)] tabular-nums">{a.chats} chats from {a.clicks} clicks</p>
                </li>
              ))}
            </ul>
          )}
      </CardBody>
    </Card>
  );
}

function ReportSettings({ isOwner }: { isOwner: boolean }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const q = useQuery<{ weekly_email: boolean; monthly_traced_bookings: number | null }>({ queryKey: ["studio-report-settings"], queryFn: () => api.get(`${RES}/settings`).then(r => r.data) });
  const [email, setEmail] = useState(false);
  const [target, setTarget] = useState("");
  useEffect(() => { if (q.data) { setEmail(q.data.weekly_email); setTarget(q.data.monthly_traced_bookings ? String(q.data.monthly_traced_bookings) : ""); } }, [q.data]);
  const save = useMutation({
    mutationFn: () => api.put(`${RES}/settings`, { weekly_email: email, monthly_traced_bookings: target ? Number(target) : 0 }),
    onSuccess: r => { qc.setQueryData(["studio-report-settings"], r.data); qc.invalidateQueries({ queryKey: ["studio-monthly"] }); toast({ variant: "success", title: "Saved" }); },
    onError: e => toast({ variant: "error", title: "Not saved", description: studioError(e, "Try again.") }),
  });
  if (!q.data) return null;
  return (
    <Card>
      <CardHeader title="Reports" description={isOwner ? "The weekly email goes to owners and managers on Monday morning." : "Set by the owner."} />
      <CardBody>
        <form className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end" onSubmit={e => { e.preventDefault(); save.mutate(); }}>
          <fieldset disabled={!isOwner || save.isPending} className="contents">
            <label className="flex min-h-11 items-center gap-2 text-sm text-[var(--haip-fg-2)]">
              <input type="checkbox" className="size-4" checked={email} onChange={e => setEmail(e.target.checked)} /> Email the weekly report
            </label>
            <label className="space-y-1"><span className="text-[13px] font-semibold text-[var(--haip-fg-2)]">Monthly target: bookings traced to marketing</span>
              <input className={inputCls} type="number" inputMode="numeric" min={0} value={target} onChange={e => setTarget(e.target.value)} /></label>
          </fieldset>
          {isOwner && <button type="submit" className={btnPrimary} disabled={save.isPending}>Save</button>}
        </form>
      </CardBody>
    </Card>
  );
}
