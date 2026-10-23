"use client";
// The weekly Insights report (GET /marketing/studio/insights): numbers computed by HAIP, the AI only explains them.
// Every figure names its period; confidence is one of Strong / Early signal / Not enough data.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { formatINR } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardBody, CardHeader, EmptyState, Stat, StatusPill, type Tone } from "@/components/ui/kit";
import { STUDIO, btn, day, studioError } from "./types";

type Word = "Strong" | "Early signal" | "Not enough data";
interface Item { text: string; confidence: Word; explanation?: string | null }
interface Steps { chats: number; people: number; qualified: number; bookings: number; revenue: number }
interface AdsFunnel extends Steps { spend: number; cost_per_chat: number | null; cost_per_lead: number | null;
  cost_per_qualified: number | null; cost_per_booking: number | null; roas: number | null }
interface Ad { ad_id: string; name: string | null; campaign: string | null; spend: number; chats: number; qualified: number;
  bookings: number; cost_per_qualified: number | null; hook_rate: number | null; hold_rate: number | null; confidence: Word }
interface Post { media_id: string; format: string; posted_at: string; reach: number; views: number | null;
  reach_vs_median: number | null; engagement_vs_median: number | null; skip_rate: number | null; confidence: Word;
  why_not_judged: string | null; funnel: Steps | null }
interface ElementValue { value: string; items: number; lift: number | null; low: number | null; high: number | null; confidence: Word; judged: boolean }
interface ElementSet { metric: string; tagged: number; median_rate: number | null; fields: Record<string, { label: string; values: ElementValue[] }> }
interface PlanItem { what: string; check_metric: string; check_by: string; confidence: Word }
interface Report {
  id: string; period: { from: string; to: string }; source: string; created_at: string;
  brief: { headline: string; wins: Item[]; problems: Item[]; actions: Item[] };
  facts: {
    funnel: { ads: AdsFunnel; organic: Steps; by_campaign: (AdsFunnel & { campaign: string })[] };
    ads: Ad[]; posts: Post[]; elements: { posts: ElementSet; ads: ElementSet };
    fatigue: { ad_id: string; name: string; frequency: number; advice: string }[];
    context: { spend: number; spend_previous_week: number; posts: number; posts_previous_week: number;
      occasions: { date: string; name: string }[] };
    next_plan: { do_more: PlanItem[]; stop: PlanItem[]; test: PlanItem[] };
    minimums: { ad_impressions: number; ad_chats: number; reel_age_days: number; group_items: number };
  };
}

const TONE: Record<Word, Tone> = { Strong: "success", "Early signal": "info", "Not enough data": "neutral" };
const pct = (v: number | null | undefined) => (v == null ? "—" : `${Math.round(v * 1000) / 10}%`);
const money = (v: number | null | undefined) => (v == null ? "—" : formatINR(v));
const times = (v: number | null | undefined) => (v == null ? "—" : `${v}x`);

function Verdict({ title, items, tone }: { title: string; items: Item[]; tone: Tone }) {
  return (
    <div className="space-y-2">
      <p className="text-[13px] font-bold text-[var(--haip-fg)]">{title}</p>
      {!items.length ? <p className="text-xs text-[var(--haip-fg-subtle)]">Nothing to report with confidence.</p> : (
        <ul className="space-y-2">
          {items.map((i, n) => (
            <li key={n} className="rounded-xl border border-[var(--haip-border)] p-3 text-sm">
              <p className="text-[var(--haip-fg)]">{i.text} <StatusPill tone={tone === "danger" ? "danger" : TONE[i.confidence]} className="ml-1">{i.confidence}</StatusPill></p>
              {i.explanation && <p className="mt-1 text-xs text-[var(--haip-fg-muted)]">{i.explanation}</p>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function InsightsReport() {
  const qc = useQueryClient();
  const { toast } = useToast();
  const q = useQuery<{ report: Report | null }>({ queryKey: ["studio-insights"], queryFn: () => api.get(`${STUDIO}/insights`).then(r => r.data) });
  const run = useMutation({
    mutationFn: () => api.post(`${STUDIO}/insights/run`),
    onSuccess: () => { toast({ variant: "success", title: "Recomputing last week", description: "Refresh in a minute." }); setTimeout(() => qc.invalidateQueries({ queryKey: ["studio-insights"] }), 20000); },
    onError: e => toast({ variant: "error", title: "Not started", description: studioError(e, "Try again.") }),
  });
  if (q.isLoading) return <Skeleton className="h-64 w-full" />;
  if (q.isError) return <Card><EmptyState title="Could not load the insights report" hint={studioError(q.error, "Try again.")} action={<button type="button" className={btn} onClick={() => q.refetch()}>Try again</button>} /></Card>;
  const r = q.data?.report;
  if (!r) return (
    <Card><EmptyState title="No insights report yet" hint="The first one is written on Monday from 08:00 for the week before. You can also make it now."
      action={<button type="button" className={btn} disabled={run.isPending} onClick={() => run.mutate()}>Make last week's report</button>} /></Card>
  );
  const f = r.facts;
  const period = `${day(r.period.from)} – ${day(r.period.to)}`;
  return (
    <div className="space-y-4">
      <Card className="p-4">
        <p className="text-xs text-[var(--haip-fg-subtle)]">Week of {period}{r.source === "deterministic" ? " · written without the AI" : ""}</p>
        <p className="mt-1 text-base font-bold text-[var(--haip-fg)]">{r.brief.headline}</p>
        <button type="button" className={`${btn} mt-3`} disabled={run.isPending} onClick={() => run.mutate()}>Recompute</button>
      </Card>

      <Card>
        <CardHeader title="Verdict" description="Three wins, three problems, three actions. The confidence word says how sure the numbers are." />
        <CardBody className="grid gap-4 md:grid-cols-3">
          <Verdict title="Wins" items={r.brief.wins} tone="success" />
          <Verdict title="Problems" items={r.brief.problems} tone="danger" />
          <Verdict title="Actions" items={r.brief.actions} tone="info" />
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Money funnel" description={`${period}. Chats traced to an ad or post; leads = people who gave a phone number; qualified = in a valid stage.`} />
        <CardBody className="space-y-3">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-6">
            <Stat label="Ad spend" value={money(f.funnel.ads.spend)} />
            <Stat label="Chats" value={f.funnel.ads.chats} hint={`${money(f.funnel.ads.cost_per_chat)} each`} />
            <Stat label="Leads" value={f.funnel.ads.people} hint={`${money(f.funnel.ads.cost_per_lead)} each`} />
            <Stat label="Qualified" value={f.funnel.ads.qualified} hint={`${money(f.funnel.ads.cost_per_qualified)} each`} />
            <Stat label="Booked" value={f.funnel.ads.bookings} hint={`${money(f.funnel.ads.cost_per_booking)} each`} />
            <Stat label="Revenue" value={money(f.funnel.ads.revenue)} hint={`ROAS ${f.funnel.ads.roas ?? "—"}`} />
          </div>
          <p className="text-xs text-[var(--haip-fg-muted)]">Organic posts: {f.funnel.organic.chats} chats, {f.funnel.organic.people} leads, {f.funnel.organic.qualified} qualified, {f.funnel.organic.bookings} booked ({money(f.funnel.organic.revenue)}).</p>
          {!!f.funnel.by_campaign.length && (
            <ul className="divide-y divide-[var(--haip-border)] text-sm">
              {f.funnel.by_campaign.map(c => (
                <li key={c.campaign} className="flex flex-wrap justify-between gap-2 py-2">
                  <span className="font-semibold">{c.campaign}</span>
                  <span className="text-[var(--haip-fg-muted)] tabular-nums">{money(c.spend)} · {c.chats} chats · {c.qualified} qualified · {c.bookings} booked · per qualified {money(c.cost_per_qualified)}</span>
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Ad leaderboard" description={`Last 28 days to ${day(r.period.to)}, best cost per qualified lead first, then hook and hold rate. Judged from ${f.minimums.ad_impressions.toLocaleString("en-IN")} impressions and ${f.minimums.ad_chats} chats.`} />
        <CardBody>
          {!f.ads.length ? <p className="text-sm text-[var(--haip-fg-subtle)]">No ads ran in this period.</p> : (
            <ul className="space-y-2">
              {f.ads.map(a => (
                <li key={a.ad_id} className="rounded-xl border border-[var(--haip-border)] p-3 text-sm">
                  <p className="font-semibold">{a.name ?? a.ad_id} <StatusPill tone={TONE[a.confidence]} className="ml-1">{a.confidence}</StatusPill></p>
                  <p className="mt-1 text-xs text-[var(--haip-fg-muted)] tabular-nums">{money(a.spend)} · {a.chats} chats · {a.qualified} qualified ({money(a.cost_per_qualified)} each) · {a.bookings} booked · hook {pct(a.hook_rate)} · hold {pct(a.hold_rate)}</p>
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Posts this week" description={`Each post against your own median for its format over the 30 days before. Reels are judged at ${f.minimums.reel_age_days} days old.`} />
        <CardBody>
          {!f.posts.length ? <p className="text-sm text-[var(--haip-fg-subtle)]">No posts in {period}.</p> : (
            <ul className="space-y-2">
              {f.posts.map(p => (
                <li key={p.media_id} className="rounded-xl border border-[var(--haip-border)] p-3 text-sm">
                  <p className="font-semibold capitalize">{p.format} · {day(p.posted_at.slice(0, 10))} <StatusPill tone={TONE[p.confidence]} className="ml-1">{p.confidence}</StatusPill></p>
                  <p className="mt-1 text-xs text-[var(--haip-fg-muted)] tabular-nums">Reach {p.reach.toLocaleString("en-IN")} ({times(p.reach_vs_median)} usual) · engagement {times(p.engagement_vs_median)} usual{p.skip_rate != null ? ` · skip rate ${p.skip_rate}%` : ""}{p.funnel ? ` · ${p.funnel.chats} chats, ${p.funnel.bookings} booked` : ""}</p>
                  {p.why_not_judged && <p className="text-xs text-[var(--haip-fg-subtle)]">Not judged yet: {p.why_not_judged}.</p>}
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="What works, by element" description={`Groups of ${f.minimums.group_items}+ posts or ads, pulled toward your own median so a few lucky posts do not decide. Range = the likely band.`} />
        <CardBody className="space-y-4">
          {(["posts", "ads"] as const).map(scope => {
            const set = f.elements[scope];
            const fields = Object.entries(set.fields);
            return (
              <div key={scope}>
                <p className="text-[13px] font-bold">{scope === "posts" ? "Posts" : "Ads"} <span className="font-normal text-[var(--haip-fg-subtle)]">· {set.metric} · median {pct(set.median_rate)} · {set.tagged} tagged</span></p>
                {!fields.length ? <p className="text-xs text-[var(--haip-fg-subtle)]">Not enough data yet: fewer than {f.minimums.group_items} tagged items share any element.</p> : (
                  <ul className="mt-1 space-y-1 text-sm">
                    {fields.map(([key, fl]) => fl.values.filter(v => v.judged).map(v => (
                      <li key={`${key}-${v.value}`} className="flex flex-wrap items-center justify-between gap-2">
                        <span>{fl.label}: <b>{v.value}</b> <span className="text-xs text-[var(--haip-fg-subtle)]">({v.items})</span></span>
                        <span className="text-xs tabular-nums text-[var(--haip-fg-muted)]">{times(v.lift)} median · range {pct(v.low)}–{pct(v.high)} <StatusPill tone={TONE[v.confidence]} className="ml-1">{v.confidence}</StatusPill></span>
                      </li>
                    )))}
                  </ul>
                )}
              </div>
            );
          })}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Tired ads and context" description="Tired = frequency over 3, link taps down 20% on its first week and chats getting dearer, two weeks running." />
        <CardBody className="space-y-2 text-sm">
          {!f.fatigue.length ? <p className="text-[var(--haip-fg-subtle)]">No tired ads.</p> : f.fatigue.map(a => (
            <p key={a.ad_id}><b>{a.name}</b>: frequency {a.frequency}. {a.advice}</p>))}
          <p className="text-xs text-[var(--haip-fg-muted)]">Ad spend {money(f.context.spend)} vs {money(f.context.spend_previous_week)} the week before · {f.context.posts} posts vs {f.context.posts_previous_week}.</p>
          {!!f.context.occasions.length && <p className="text-xs text-[var(--haip-fg-muted)]">Coming up: {f.context.occasions.map(o => `${o.name} (${day(o.date)})`).join(", ")}.</p>}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Next plan" description="Fed to next week's plan. Each has a number to check and a date." />
        <CardBody className="grid gap-3 md:grid-cols-3">
          {(["do_more", "stop", "test"] as const).map(k => (
            <div key={k}>
              <p className="text-[13px] font-bold">{k === "do_more" ? "Do more" : k === "stop" ? "Stop" : "Test"}</p>
              {!f.next_plan[k].length ? <p className="text-xs text-[var(--haip-fg-subtle)]">Not enough data yet.</p> : (
                <ul className="space-y-1 text-sm">{f.next_plan[k].map((i, n) => (
                  <li key={n}>{i.what} <span className="text-xs text-[var(--haip-fg-subtle)]">· check {i.check_metric} by {day(i.check_by)}</span></li>))}</ul>
              )}
            </div>
          ))}
        </CardBody>
      </Card>
    </div>
  );
}
