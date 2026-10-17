"use client";
import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { AlertCircle, ArrowDownRight, ArrowUpRight, CheckCircle2, Clock, Eye, Megaphone, Send, Shield } from "@/lib/icons";
import { cn } from "@/lib/utils";
import api from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";
import { CampaignReport } from "@/components/messaging/CampaignReport";
import { WhatsAppHealthCard } from "@/components/messaging/WhatsAppHealthCard";
import { FailureBars, Funnel, HourChart, RateChart, VolumeChart } from "@/components/messaging/analytics/AnalyticsCharts";
import { CampaignTable, TemplateTable } from "@/components/messaging/analytics/AnalyticsTables";
import { change, fmt, pct, type Analytics } from "@/components/messaging/analytics/analyticsTypes";

const RANGES = [7, 14, 30, 90] as const;

// ─── Headline tile ───────────────────────────────────────────────────────────

function Tile({ label, value, sub, icon, delta, goodWhen = "up", tone }: {
  label: string; value: string; sub?: string; icon: React.ReactNode;
  delta?: { text: string; dir: "up" | "down" | "flat" } | null; goodWhen?: "up" | "down"; tone?: string;
}) {
  return (
    <div className="wa-viz rounded-2xl border border-[var(--haip-border)] bg-[var(--haip-card)] p-4">
      <div className={cn("flex items-center gap-1.5 text-xs font-medium text-[var(--viz-ink-2)]", tone)}>{icon}{label}</div>
      <p className="text-3xl font-bold text-[var(--viz-ink)] mt-1.5 tabular-nums tracking-tight">{value}</p>
      <div className="mt-1 flex items-center gap-2 text-[11px] text-[var(--viz-ink-2)] min-h-[16px]">
        {sub && <span>{sub}</span>}
        {delta && delta.dir !== "flat" && (
          <span className="inline-flex items-center gap-0.5 font-medium text-[var(--viz-ink)]"
            title={`${goodWhen === (delta.dir) ? "Better" : "Worse"} than the previous period`}>
            {delta.dir === "up" ? <ArrowUpRight size={12} /> : <ArrowDownRight size={12} />}{delta.text}
            <span className="font-normal text-[var(--viz-ink-3)]"> vs before</span>
          </span>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value, href }: { label: string; value: string; href?: string }) {
  const inner = (
    <div className="rounded-xl bg-[var(--haip-surface)] px-3 py-2">
      <p className="text-lg font-bold text-[var(--haip-fg)] tabular-nums leading-tight">{value}</p>
      <p className="text-[10px] text-[var(--haip-fg-muted)]">{label}</p>
    </div>
  );
  return href ? <Link href={href} className="hover:opacity-80">{inner}</Link> : inner;
}

const RATING: Record<string, { label: string; cls: string }> = {
  GREEN: { label: "Quality: good", cls: "bg-green-50 text-green-700 border-green-200" },
  YELLOW: { label: "Quality: at risk", cls: "bg-amber-50 text-amber-700 border-amber-200" },
  RED: { label: "Quality: poor", cls: "bg-red-50 text-red-700 border-red-200" },
};

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function MessagingOverviewPage() {
  const [days, setDays] = useState<number>(30);
  const [report, setReport] = useState<{ id: string; name: string } | null>(null);

  const { data, isLoading, isError, refetch, isFetching } = useQuery<Analytics>({
    queryKey: ["wa-analytics", days],
    queryFn: () => api.get("/messaging/analytics", { params: { days } }).then(r => r.data),
    staleTime: 30_000,
    placeholderData: (prev) => prev,
    refetchInterval: (q) => (q.state.data?.running ? 15_000 : false),
  });
  // Meta's own read on the number's health (polled hourly by the backend).
  const { data: quality } = useQuery<{ current: { quality_rating: string | null; messaging_limit_tier: string | null } }>({
    queryKey: ["meta-quality-current"],
    queryFn: () => api.get("/integrations/meta/quality", { params: { days: 1 } }).then(r => r.data).catch(() => null),
    staleTime: 5 * 60_000,
  });

  const t = data?.totals;
  const p = data?.previous;
  const nothing = !!data && data.totals.sent + data.totals.failed === 0 && data.campaigns.length === 0;
  const rating = quality?.current?.quality_rating ? RATING[quality.current.quality_rating] : null;

  return (
    <div className="h-full flex flex-col">
      <div className="px-6 py-5 bg-[var(--haip-card)] border-b border-[var(--haip-border)] flex-shrink-0">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div>
            <h1 className="haip-page-title">WhatsApp overview</h1>
            <p className="text-sm text-[var(--haip-fg-muted)] mt-0.5">How your campaigns are doing: what was sent, what arrived, what was read, and what failed.</p>
          </div>
          <div className="flex items-center gap-2">
            <div className="inline-flex rounded-xl bg-[var(--haip-surface)] p-0.5" role="tablist" aria-label="Period">
              {RANGES.map(r => (
                <button key={r} role="tab" aria-selected={days === r} onClick={() => setDays(r)}
                  className={cn("px-3 py-1.5 rounded-[10px] text-xs font-medium transition-colors",
                    days === r ? "bg-[var(--haip-card)] text-[var(--haip-fg)] shadow-sm" : "text-[var(--haip-fg-muted)] hover:text-[var(--haip-fg)]")}>
                  {r} days
                </button>
              ))}
            </div>
            <Link href="/dashboard/messaging/campaigns" className="flex items-center gap-2 bg-primary text-white px-4 py-2.5 rounded-xl text-sm font-semibold hover:bg-primary transition-colors shadow-sm shadow-[color-mix(in_srgb,var(--primary)_18%,transparent)]">
              <Megaphone size={15} /> New campaign
            </Link>
          </div>
        </div>

        {/* Health strip */}
        {data && (
          <div className="flex flex-wrap items-center gap-2 mt-4 text-xs">
            <span className={cn("inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border font-medium",
              data.health.connected ? "bg-green-50 text-green-700 border-green-200" : "bg-red-50 text-red-700 border-red-200")}>
              {data.health.connected ? <CheckCircle2 size={12} /> : <AlertCircle size={12} />}
              {data.health.connected ? "WhatsApp connected" : "WhatsApp not connected"}
            </span>
            {rating && (
              <Link href="/dashboard/settings/integrations/meta-quality" className={cn("inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border font-medium", rating.cls)}>
                <Shield size={12} /> {rating.label}
                {quality?.current?.messaging_limit_tier && <span className="font-normal opacity-80">· limit {quality.current.messaging_limit_tier.replace("TIER_", "").replace(/_/g, " ").toLowerCase()}</span>}
              </Link>
            )}
            <Link href="/dashboard/messaging/templates" className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-[var(--haip-border)] text-[var(--haip-fg-2)] hover:bg-[var(--haip-surface)]">
              Templates: {data.health.templates.approved} approved
              {data.health.templates.pending > 0 && ` · ${data.health.templates.pending} in review`}
              {data.health.templates.rejected + data.health.templates.submission_failed > 0 && ` · ${data.health.templates.rejected + data.health.templates.submission_failed} need attention`}
            </Link>
          </div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        <WhatsAppHealthCard />
        {isError && !data ? (
          <div className="py-20 text-center">
            <AlertCircle size={32} className="text-red-300 mx-auto mb-3" />
            <p className="text-sm text-[var(--haip-fg)] font-medium">Couldn't load the overview</p>
            <button onClick={() => refetch()} disabled={isFetching} className="mt-4 text-xs font-semibold text-primary border border-[color-mix(in_srgb,var(--primary)_25%,transparent)] bg-[var(--haip-primary-tint)] px-3 py-1.5 rounded-lg">{isFetching ? "Retrying…" : "Retry"}</button>
          </div>
        ) : isLoading && !data ? (
          <div className="space-y-4"><div className="grid grid-cols-2 lg:grid-cols-4 gap-4">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-28 rounded-2xl" />)}</div><Skeleton className="h-64 rounded-2xl" /></div>
        ) : nothing ? (
          <div className="py-20 text-center">
            <Send size={40} className="text-[var(--haip-fg-subtle)]/70 mx-auto mb-3" />
            <p className="text-sm text-[var(--haip-fg)] font-medium">Nothing sent in the last {days} days</p>
            <p className="text-xs text-[var(--haip-fg-muted)] mt-1">Once a campaign goes out, delivery, reads and failures show up here.</p>
            {data && data.upcoming.length > 0 && <p className="text-xs text-[var(--haip-fg-2)] mt-3">Next up: <strong>{data.upcoming[0].name}</strong>{data.upcoming[0].scheduled_at ? `, ${new Date(data.upcoming[0].scheduled_at).toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })}` : ""}</p>}
          </div>
        ) : data && t && p && (
          <>
            {data.truncated && <p className="text-xs text-amber-700 bg-amber-50 rounded-xl px-3 py-2">Very large period — only the first 300,000 messages are counted. Choose a shorter range for exact numbers.</p>}

            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
              <Tile label="Sent" value={fmt(t.sent)} sub={`across ${fmt(t.campaigns)} campaign${t.campaigns === 1 ? "" : "s"}`} icon={<Send size={13} />} delta={change(t.sent, p.sent, "count")} />
              <Tile label="Delivered" value={pct(t.delivery_rate)} sub={`${fmt(t.delivered)} messages`} icon={<CheckCircle2 size={13} />} delta={change(t.delivery_rate, p.delivery_rate, "points")} />
              <Tile label="Read" value={pct(t.read_rate)} sub={`${fmt(t.read)} messages`} icon={<Eye size={13} />} delta={change(t.read_rate, p.read_rate, "points")} />
              <Tile label="Failed" value={pct(t.failure_rate)} sub={`${fmt(t.failed)} messages`} icon={<AlertCircle size={13} />} tone="text-[var(--viz-fail)]" goodWhen="down" delta={change(t.failure_rate, p.failure_rate, "points")} />
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <Stat label="Campaigns run" value={fmt(t.campaigns)} href="/dashboard/messaging/campaigns" />
              <Stat label="Sending now" value={fmt(data.running)} />
              <Stat label="Scheduled" value={fmt(data.upcoming.length)} href="/dashboard/messaging/campaigns" />
              <Stat label="Opted out" value={fmt(t.opt_outs)} href="/dashboard/messaging/subscribers" />
            </div>

            <div className="grid lg:grid-cols-2 gap-4">
              <VolumeChart daily={data.daily} />
              <RateChart daily={data.daily} />
            </div>
            <div className="grid lg:grid-cols-2 gap-4">
              <Funnel totals={t} />
              <FailureBars failures={data.failures} />
            </div>
            <HourChart hours={data.hours} best={data.best_hour} />

            <section className="wa-viz rounded-2xl border border-[var(--haip-border)] bg-[var(--haip-card)]">
              <div className="px-5 pt-4 pb-2 flex items-center justify-between">
                <h3 className="text-sm font-semibold text-[var(--viz-ink)]">Campaigns</h3>
                <span className="text-[11px] text-[var(--viz-ink-3)]">Select one for its full report</span>
              </div>
              {data.campaigns.length === 0 ? <p className="px-5 pb-5 text-xs text-[var(--viz-ink-3)]">No campaigns in this period.</p>
                : <CampaignTable rows={data.campaigns} onOpen={c => setReport({ id: c.id, name: c.name })} />}
            </section>

            <section className="wa-viz rounded-2xl border border-[var(--haip-border)] bg-[var(--haip-card)]">
              <div className="px-5 pt-4 pb-2"><h3 className="text-sm font-semibold text-[var(--viz-ink)]">Templates</h3>
                <p className="text-[11px] text-[var(--viz-ink-2)] mt-0.5">Which messages perform best</p></div>
              {data.templates.length === 0 ? <p className="px-5 pb-5 text-xs text-[var(--viz-ink-3)]">No template activity in this period.</p> : <TemplateTable rows={data.templates} />}
            </section>

            {data.upcoming.length > 0 && (
              <section className="rounded-2xl border border-[var(--haip-border)] bg-[var(--haip-card)] p-5">
                <h3 className="text-sm font-semibold text-[var(--haip-fg)] mb-2 flex items-center gap-1.5"><Clock size={14} /> Coming up</h3>
                <ul className="divide-y divide-[var(--haip-border)] text-xs">
                  {data.upcoming.map(u => (
                    <li key={u.id} className="py-2 flex items-center justify-between">
                      <span className="font-medium text-[var(--haip-fg)]">{u.name}</span>
                      <span className="text-[var(--haip-fg-muted)]">{u.scheduled_at ? new Date(u.scheduled_at).toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }) : "—"}</span>
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </>
        )}
      </div>

      {report && <CampaignReport campaignId={report.id} campaignName={report.name} onClose={() => setReport(null)} />}
    </div>
  );
}
