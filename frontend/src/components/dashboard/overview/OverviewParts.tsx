"use client";
// The pieces of Home's Overview (owner, 28 Nov 2026), shared by the phone and the desktop layout so the two can never
// disagree. Order follows the one decision made here: who needs someone now, then the period's numbers, then the trend.
// Every figure is the server's: the business overview (GET /dashboard/business-overview), the ONE work queue
// (GET /work-queue, same query key as My day and the Now button) and the bookings list for the next 7 days. Nothing here
// computes a business number, a figure the role may not see is "Hidden" (never 0), and each chart's title is the question
// it answers.
import type { ReactNode } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { cn, formatINR } from "@/lib/utils";
import { ArrowRight, Calendar, CalendarCheck, CheckCircle2, LogIn, LogOut, MessageSquare, Phone, PhoneMissed, Reply, Target, Users, Wallet } from "@/lib/icons";
import { Skeleton } from "@/components/ui/skeleton";
import { GuestAvatar } from "@/components/crm/GuestAvatar";
import { ChannelIcon, channelLabel } from "@/components/inbox/ChannelIcon";
import { AvatarChannelBadges, toGuestChannel } from "@/components/inbox/ChannelBadges";
import { CompactRow, KpiTile, MiniBars, RowList, TileFact, type Bar } from "@/components/ui/kit";
import { guestName, shortDay, todayIST, type AgendaRow } from "@/lib/bookingAgenda";
import { lakh, restricted } from "@/components/dashboard/command/owner";
import type { Overview } from "@/components/dashboard/command/CommandCenter";
import type { SeriesBlock } from "@/components/dashboard/command/types";

// ── the work queue ──────────────────────────────────────────────────────────────────────────────────────────

type Severity = "fresh" | "late" | "urgent" | "critical" | "stale";
export interface QueueItem {
  kind: string; title: string; detail: string; action: string; href: string; guest_id: string | null;
  channels: string[]; since: string | null; severity: Severity;
}
export interface Queue { people_waiting?: number; total: number; severity?: Partial<Record<Severity, number>>; items: QueueItem[] }

export function useWorkQueue() {
  return useQuery<Queue>({
    queryKey: ["work-queue", ""],
    queryFn: () => api.get("/work-queue").then(r => r.data),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
}

/** People still waiting: the cold tail and calendar clashes are listed on My day, not counted as faces here. */
export const waitingPeople = (q: Queue | undefined): QueueItem[] => (q?.items ?? []).filter(i => i.severity !== "stale" && i.kind !== "clash");
const peopleCount = (q: Queue): number => q.people_waiting ?? Math.max(0, q.total - (q.severity?.stale ?? 0));

const KIND_LABEL: Record<string, string> = {
  callback: "Missed call", new_lead: "New lead", reply: "Waiting for a reply", no_reply: "Not replying to us", followup: "Follow-up due",
  came_back: "Came back", campaign_reply: "Replied to campaign", handover: "Bot handed over", consult: "Question from the AI",
};
const LATE = new Set<Severity>(["late", "urgent", "critical"]);

export function waitText(iso: string | null, now = Date.now()): string {
  if (!iso) return "";
  const m = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60000));
  if (m < 1) return "now";
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  return h < 24 ? `${h}h` : `${Math.floor(h / 24)}d`;
}

/** Calls to return, people to answer, follow-ups due: the three reasons someone is on the queue. */
export function waitingKinds(items: QueueItem[]): { calls: number; replies: number; followups: number } {
  let calls = 0, replies = 0, followups = 0;
  for (const i of items) {
    if (i.kind === "callback") calls++;
    else if (i.kind === "followup") followups++;
    else replies++;
  }
  return { calls, replies, followups };
}

/** The dark bar at the top of Home: the faces of the people waiting, how many, and the way into My day. */
export function WaitingStrip({ wide }: { wide?: boolean }) {
  const { data, isError, refetch } = useWorkQueue();
  if (isError) {
    return (
      <div role="alert" className="haip-card px-4 py-3 text-[13px] text-[var(--haip-fg-2)]">
        Couldn&apos;t load who is waiting. <button type="button" onClick={() => refetch()} className="min-h-11 cursor-pointer font-semibold text-primary underline">Try again</button>
      </div>
    );
  }
  if (!data) return <Skeleton className={cn("rounded-[14px]", wide ? "h-14" : "h-[52px]")} aria-label="Loading who is waiting" />;
  const people = waitingPeople(data);
  const n = peopleCount(data);
  const kinds = waitingKinds(people);
  const base = "flex items-center gap-2.5 rounded-[14px] bg-[var(--haip-stat-dark-bg)] text-[var(--haip-stat-dark-fg)] transition-transform duration-150 active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2";
  if (n === 0) {
    return (
      <Link href="/dashboard/my-day" className={cn(base, "min-h-[52px] px-3.5 py-2")}>
        <CheckCircle2 size={20} className="shrink-0 text-[var(--haip-stat-dark-chip)]" aria-hidden />
        <span className="min-w-0 flex-1 text-[14px] font-semibold">Nobody is waiting. Every lead has been contacted.</span>
      </Link>
    );
  }
  return (
    <Link href="/dashboard/my-day" aria-label={`${n} ${n === 1 ? "person" : "people"} waiting. Open My day`}
      className={cn(base, "@container min-h-[52px] py-1.5 pl-2.5 pr-1.5", wide && "min-h-14 gap-4 pl-3.5")}>
      <span aria-hidden className="flex shrink-0">
        {people.slice(0, wide ? 5 : 4).map((p, i) => (
          <span key={`${p.guest_id ?? p.href}:${i}`} className={cn("rounded-full ring-2 ring-[var(--haip-stat-dark-bg)]", i > 0 && "-ml-1.5", i > 1 && "hidden @[330px]:block")}>
            <GuestAvatar name={p.title} size="sm" />
          </span>
        ))}
      </span>
      <span className="font-[family-name:var(--font-display)] text-[24px] font-bold leading-none tabular-nums text-[var(--haip-stat-dark-chip)]">{n}</span>
      <span className="min-w-0 truncate text-[14px] font-bold">{wide ? "waiting for your team" : "waiting"}</span>
      {wide && (
        <span aria-hidden className="hidden items-center gap-4 text-[13px] font-semibold text-[var(--haip-stat-dark-muted)] md:flex">
          {kinds.calls > 0 && <span className="inline-flex items-center gap-1.5"><PhoneMissed size={15} /><span className="tabular-nums">{kinds.calls}</span></span>}
          {kinds.replies > 0 && <span className="inline-flex items-center gap-1.5"><MessageSquare size={15} /><span className="tabular-nums">{kinds.replies}</span></span>}
          {kinds.followups > 0 && <span className="inline-flex items-center gap-1.5"><Reply size={15} /><span className="tabular-nums">{kinds.followups}</span></span>}
        </span>
      )}
      <span className={cn("ml-auto inline-flex shrink-0 items-center justify-center gap-1.5 rounded-xl font-bold",
        wide ? "min-h-10 bg-[var(--haip-logo-bg)] px-4 text-[13.5px] text-[var(--haip-logo-fg)]" : "size-10 bg-[color-mix(in_srgb,var(--haip-stat-dark-fg)_14%,transparent)]")}>
        {wide && "Open My day"}<ArrowRight size={wide ? 16 : 19} aria-hidden />
      </span>
    </Link>
  );
}

// ── the period's numbers ────────────────────────────────────────────────────────────────────────────────────

const recent = (a: number[] | null | undefined, n = 7): number[] | null => (a && a.length > 1 ? a.slice(-n) : null);

/** New leads, calls, bookings and booked value for the period, each on its domain colour with its last days as a line. */
export function OverviewTiles({ data, periodLabel, className }: { data: Overview; periodLabel: string; className?: string }) {
  const kpis = data.owner?.kpis;
  if (!kpis) return null;
  const s = data.series;
  const calls = data.owner?.ai_calls?.calls;
  const topSources = data.sources.filter(r => r.leads > 0).slice(0, 2);
  return (
    <section aria-label={`Numbers, ${periodLabel}`} className={cn("grid grid-cols-2 gap-2 lg:grid-cols-4 lg:gap-3", className)}>
      <KpiTile tone="lead" icon={Users} label="New leads" value={kpis.new_leads.count} href="/dashboard/leads"
        trend={recent(s.leads)} trendLabel={trendLabel("New leads", s.leads)}
        facts={topSources.map(r => (
          <TileFact key={r.key} label={`${r.leads} from ${channelLabel(r.key) === "Other" ? r.label : channelLabel(r.key)}`}>
            <ChannelIcon channel={r.key} showBg={false} />{r.leads}
          </TileFact>
        ))} />
      {calls && (
        <KpiTile tone="call" icon={Phone} label="Calls" value={calls.total} href={calls.href}
          trend={recent(s.calls)} trendLabel={trendLabel("Calls", s.calls)}
          facts={calls.missed > 0 ? <TileFact tone="danger" label={`${calls.missed} missed`}><PhoneMissed size={12} aria-hidden />{calls.missed}</TileFact> : undefined} />
      )}
      {restricted(kpis.bookings)
        ? <KpiTile tone="book" icon={CalendarCheck} label="Bookings" value="" locked href="/dashboard/bookings" />
        : <KpiTile tone="book" icon={CalendarCheck} label="Bookings" value={kpis.bookings.count} href="/dashboard/bookings"
            trend={recent(s.bookings)} trendLabel={trendLabel("Bookings", s.bookings)} />}
      {restricted(kpis.booked_value)
        ? <KpiTile tone="book" icon={Wallet} label="Booked value" value="" locked href="/dashboard/targets" />
        : <KpiTile tone="book" icon={Wallet} label="Booked value" value={lakh(kpis.booked_value.total)} href="/dashboard/targets"
            trend={recent(s.booking_value)} trendLabel={trendLabel("Booked value in rupees", s.booking_value)} />}
    </section>
  );
}

function trendLabel(what: string, values: number[] | null | undefined): string | undefined {
  const r = recent(values);
  return r ? `${what}, last ${r.length} days: ${r.join(", ")}` : undefined;
}

// ── charts ──────────────────────────────────────────────────────────────────────────────────────────────────

function dayParts(iso: string): { day: string; long: string } {
  const d = new Date(`${iso}T12:00:00+05:30`);
  return {
    day: String(d.toLocaleDateString("en-IN", { day: "numeric", timeZone: "Asia/Kolkata" })),
    long: d.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", timeZone: "Asia/Kolkata" }),
  };
}

/** One bar per day of the server's series. Exported for tests. */
export function leadBars(s: SeriesBlock, today = todayIST()): Bar[] {
  return s.days.map((iso, i) => {
    const p = dayParts(iso), v = s.leads[i] ?? 0;
    return { label: p.day, value: v, now: iso === today, tip: `${p.long}: ${v} new ${v === 1 ? "lead" : "leads"}` };
  });
}

export function callBars(s: SeriesBlock, today = todayIST()): Bar[] | null {
  if (!s.calls || !s.calls_missed) return null;
  return s.days.map((iso, i) => {
    const p = dayParts(iso), total = s.calls![i] ?? 0, missed = Math.min(total, s.calls_missed![i] ?? 0);
    return { label: p.day, value: total - missed, top: missed, now: iso === today, tip: `${p.long}: ${total - missed} answered, ${missed} missed` };
  });
}

const card = "haip-card flex min-w-0 flex-col gap-2 px-3.5 py-2.5";
const cardTitle = "flex min-w-0 items-center gap-2 text-[14px] font-bold text-[var(--haip-fg)]";
const cardPeriod = "ml-auto shrink-0 text-[12px] font-semibold tabular-nums text-[var(--haip-fg-subtle)]";

/** "How many new leads came in each day?" */
export function LeadsChart({ data, height = 112, yAxis, className }: { data: Overview; height?: number; yAxis?: boolean; className?: string }) {
  const bars = leadBars(data.series);
  const total = bars.reduce((n, b) => n + b.value, 0);
  return (
    <Link href="/dashboard/leads" className={cn(card, "transition-transform duration-150 active:scale-[0.99] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50", className)}>
      <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className={cardTitle}><Users size={15} className="shrink-0 text-primary" aria-hidden />New leads per day</span>
        <span className={cardPeriod}>{bars.length} days · {total}</span>
      </span>
      <MiniBars bars={bars} height={height} yAxis={yAxis} label="New leads per day" />
    </Link>
  );
}

/** "How many calls did we answer and miss each day?" Only for people who see the whole workspace. */
export function CallsChart({ data, height = 112, className }: { data: Overview; height?: number; className?: string }) {
  const bars = callBars(data.series);
  if (!bars) return null;
  return (
    <Link href="/dashboard/calls" className={cn(card, "transition-transform duration-150 active:scale-[0.99] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50", className)}>
      <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className={cardTitle}><Phone size={15} className="shrink-0 text-[var(--haip-dom-call-ink)]" aria-hidden />Calls per day</span>
        <span className="flex items-center gap-3 text-[12px] font-semibold text-[var(--haip-fg-subtle)]">
          <span className="inline-flex items-center gap-1.5"><span aria-hidden className="size-2.5 rounded-[3px] bg-[var(--haip-viz-answered)]" />Answered</span>
          <span className="inline-flex items-center gap-1.5"><span aria-hidden className="size-2.5 rounded-[3px] bg-[var(--haip-viz-missed)]" /><PhoneMissed size={12} aria-hidden />Missed</span>
        </span>
        <span className={cardPeriod}>{bars.length} days</span>
      </span>
      <MiniBars bars={bars} height={height} yAxis label="Calls answered and missed per day" />
    </Link>
  );
}

const FUNNEL_ICON = { identified: Users, qualified: Calendar, booked: CalendarCheck, paid: Wallet } as const;
// One word per step so the label never truncates in a narrow card; the server's full label stays as the tooltip.
const FUNNEL_SHORT: Record<string, string> = { identified: "Leads", qualified: "Qualified", booked: "Booked", paid: "Paid" };

/** "Of the people who became leads in the period, how many went on to book and pay?" (the server's cohort funnel). */
export function FunnelCard({ data, periodLabel, className }: { data: Overview; periodLabel: string; className?: string }) {
  const stages = data.funnel.stages;
  const top = stages[0]?.count ?? 0;
  return (
    <section aria-label={`From lead to booking, ${periodLabel}`} title={data.funnel.basis} className={cn(card, className)}>
      <span className="flex items-center gap-2">
        <span className={cardTitle}><Target size={15} className="shrink-0 text-primary" aria-hidden />From lead to booking</span>
        <span className={cardPeriod}>{periodLabel}</span>
      </span>
      {top === 0 ? (
        <p className="py-3 text-[13px] text-[var(--haip-fg-subtle)]">No new leads in this period yet, so there is nothing to follow through.</p>
      ) : (
        <ul className="grid gap-1 sm:gap-1.5">
          {stages.map(st => {
            const Icon = FUNNEL_ICON[st.key] ?? Users;
            const share = Math.round((st.count / top) * 100);
            return (
              <li key={st.key} title={st.label} className="grid grid-cols-[5.25rem_minmax(0,1fr)_auto] items-center gap-2.5 text-[13px]">
                <span className="flex min-w-0 items-center gap-1.5 font-semibold text-[var(--haip-fg)]"><Icon size={14} className="shrink-0 text-[var(--haip-fg-subtle)]" aria-hidden /><span className="truncate">{FUNNEL_SHORT[st.key] ?? st.label}</span></span>
                <svg aria-hidden className="h-2.5 w-full overflow-hidden rounded-full">
                  <rect width="100%" height="100%" className="fill-[var(--haip-primary-tint)]" />
                  <rect width={`${share}%`} height="100%" rx="5" className="fill-primary" />
                </svg>
                <span className="whitespace-nowrap text-right font-bold tabular-nums text-[var(--haip-fg)]">{st.count}<span className="ml-1 font-medium text-[var(--haip-fg-subtle)]">{share}%</span></span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

// ── the next 7 days ─────────────────────────────────────────────────────────────────────────────────────────

function WeekStat({ icon: Icon, label, value, href }: { icon: typeof LogIn; label: string; value: string | number; href: string }) {
  return (
    <Link href={href} className="@container flex min-h-12 min-w-0 items-center gap-2.5 px-3 py-1.5 transition-colors hover:bg-[var(--haip-surface)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary/50">
      <span aria-hidden className="hidden size-8 shrink-0 items-center justify-center @[9.5rem]:flex rounded-[9px] bg-[var(--haip-dom-book-bg)] text-[var(--haip-dom-book-ink)]"><Icon size={16} /></span>
      <span className="flex min-w-0 flex-col">
        <span className="truncate text-[11.5px] font-semibold text-[var(--haip-fg-subtle)]">{label}</span>
        <span className="whitespace-nowrap font-[family-name:var(--font-display)] text-[clamp(16px,9cqi,22px)] font-bold leading-tight tabular-nums text-[var(--haip-fg)]">{value}</span>
      </span>
    </Link>
  );
}

/** Check-ins, check-outs and money still due on trips starting in the next 7 days. */
export function WeekRow({ checkIns, checkOuts, due, loading, className }: {
  checkIns: number | null; checkOuts: number | null; due: number | null; loading?: boolean; className?: string;
}) {
  if (loading) return <Skeleton className={cn("h-[52px] rounded-[var(--radius)]", className)} aria-label="Loading the next 7 days" />;
  return (
    <section aria-label="Next 7 days" className={cn("haip-card grid overflow-hidden divide-x divide-[var(--haip-border)]", checkOuts != null ? "grid-cols-3" : "grid-cols-2", className)}>
      {checkIns != null && <WeekStat icon={LogIn} label="Check-ins · 7 days" value={checkIns} href="/dashboard/bookings" />}
      {checkOuts != null && <WeekStat icon={LogOut} label="Check-outs · 7 days" value={checkOuts} href="/dashboard/bookings" />}
      {due != null && <WeekStat icon={Wallet} label="To collect · 7 days" value={lakh(due)} href="/dashboard/bookings" />}
    </section>
  );
}

// ── short lists ─────────────────────────────────────────────────────────────────────────────────────────────

function ListCard({ title, icon: Icon, more, children, className }: {
  title: string; icon: typeof Users; more?: { href: string; label: string }; children: ReactNode; className?: string;
}) {
  return (
    <section aria-label={title} className={cn("min-w-0", className)}>
      <div className="mb-1 flex items-center gap-2 px-1">
        <h2 className={cardTitle}><Icon size={15} className="shrink-0 text-[var(--haip-fg-subtle)]" aria-hidden />{title}</h2>
        {/* 36px tall to keep the first screen; the ::after stretches the touch area to 44px */}
        {more && <Link href={more.href} className="relative ml-auto inline-flex min-h-9 items-center gap-1 text-[12.5px] font-bold text-primary after:absolute after:-inset-x-2 after:-inset-y-1 after:content-[''] hover:underline">{more.label}<ArrowRight size={13} aria-hidden /></Link>}
      </div>
      {children}
    </section>
  );
}

/** The first few people from the work queue, worst first. Opening a row goes to the person; calling happens there. */
export function WaitingList({ limit = 3, className }: { limit?: number; className?: string }) {
  const { data, isPending, isError, refetch } = useWorkQueue();
  const people = waitingPeople(data);
  return (
    <ListCard title="Waiting for you" icon={MessageSquare} className={className}
      more={people.length > 0 ? { href: "/dashboard/my-day", label: people.length > limit ? `All ${people.length}` : "My day" } : undefined}>
      {isPending ? (
        <div className="grid gap-1.5" aria-busy="true" aria-label="Loading who is waiting">{Array.from({ length: limit }, (_, i) => <Skeleton key={i} className="h-[56px] rounded-xl" />)}</div>
      ) : isError ? (
        <p role="alert" className="haip-card px-4 py-3 text-[13px] text-[var(--haip-fg-2)]">Couldn&apos;t load who is waiting. <button type="button" onClick={() => refetch()} className="min-h-11 cursor-pointer font-semibold text-primary underline">Try again</button></p>
      ) : people.length === 0 ? (
        <p className="haip-card flex items-center gap-2.5 px-4 py-3.5 text-[13.5px] text-[var(--haip-fg-2)]"><CheckCircle2 size={17} className="shrink-0 text-[var(--haip-status-success-fg)]" aria-hidden />Nobody is waiting on the team right now.</p>
      ) : (
        <RowList label="Waiting for you">
          {people.slice(0, limit).map((p, i) => {
            const channels = p.channels.map(toGuestChannel).filter(Boolean) as NonNullable<ReturnType<typeof toGuestChannel>>[];
            return (
              <CompactRow key={`${p.kind}:${p.guest_id ?? p.href}:${i}`} href={p.href}
                avatar={<span className="relative shrink-0"><GuestAvatar name={p.title} /><AvatarChannelBadges channels={channels} size={14} /></span>}
                title={p.title} subtitle={KIND_LABEL[p.kind] ?? p.detail}
                meta={waitText(p.since)} metaTone={LATE.has(p.severity) ? "danger" : "highlight"} />
            );
          })}
        </RowList>
      )}
    </ListCard>
  );
}

export function TripRow({ r }: { r: AgendaRow }) {
  const name = guestName(r);
  const owes = r.total_outstanding > 0;
  return (
    <CompactRow href={`/dashboard/bookings/${r.id}`} avatar={<GuestAvatar name={name} />}
      title={name}
      subtitle={[shortDay(r.checkin), r.property?.name ?? r.trip].filter(Boolean).join(" · ")}
      meta={owes ? `${formatINR(r.total_outstanding)} due` : r.total > 0 ? "Paid" : undefined}
      metaTone={owes ? (r.payment_overdue ? "danger" : "warning") : "success"} />
  );
}

/** The next trips to start, with what is still owed on each. `many` is the workspace's word ("trips" / "stays"). */
export function ArrivalsList({ rows, total, loading, error, onRetry, limit = 3, many, className }: {
  rows: AgendaRow[]; total: number; loading: boolean; error: boolean; onRetry: () => void; limit?: number; many: string; className?: string;
}) {
  return (
    <ListCard title="Arriving next" icon={LogIn} className={className}
      more={total > 0 ? { href: "/dashboard/bookings", label: total > limit ? `All ${total}` : "Bookings" } : undefined}>
      {loading ? (
        <div className="grid gap-1.5" aria-busy="true" aria-label={`Loading the next ${many}`}>{Array.from({ length: limit }, (_, i) => <Skeleton key={i} className="h-[56px] rounded-xl" />)}</div>
      ) : error ? (
        <p role="alert" className="haip-card px-4 py-3 text-[13px] text-[var(--haip-fg-2)]">Couldn&apos;t load the {many}. <button type="button" onClick={onRetry} className="min-h-11 cursor-pointer font-semibold text-primary underline">Try again</button></p>
      ) : rows.length === 0 ? (
        <p className="haip-card px-4 py-3.5 text-[13.5px] text-[var(--haip-fg-subtle)]">No {many} start in the next 7 days.</p>
      ) : (
        <RowList label="Arriving next">{rows.slice(0, limit).map(r => <TripRow key={r.id} r={r} />)}</RowList>
      )}
    </ListCard>
  );
}
