"use client";
// Home dashboard panels: revenue chart, lead funnel, team table, lead
// sources and the AI insights row.
import Link from "next/link";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { cn } from "@/lib/utils";
import { ChannelBadge } from "@/components/inbox/ChannelBadges";
import type { GuestChannel } from "@/store/inbox";
import { formatRupees, formatSeconds, type AgentRow, type Insight, type OverviewResponse, type Series } from "./types";

function Panel({ title, meta, children, className }: { title: string; meta?: string; children: React.ReactNode; className?: string }) {
  return (
    <section className={cn("haip-card p-5 min-w-0", className)}>
      <div className="flex items-baseline justify-between gap-3 mb-4">
        <h2 className="text-[15px] font-bold" style={{ color: "var(--haip-fg)" }}>{title}</h2>
        {meta && <span className="text-xs truncate" style={{ color: "var(--haip-fg-subtle)" }}>{meta}</span>}
      </div>
      {children}
    </section>
  );
}

function Empty({ text }: { text: string }) {
  return <p className="text-xs py-6 text-center" style={{ color: "var(--haip-fg-subtle)" }}>{text}</p>;
}

// ── Revenue & bookings ────────────────────────────────────────────────────────

function dayTick(iso: string, many: boolean) {
  const d = new Date(`${iso}T00:00:00`);
  return many ? String(d.getDate()) : d.toLocaleDateString("en-IN", { weekday: "short" });
}

export function RevenueChart({ series, rangeLabel }: { series: Series; rangeLabel: string }) {
  const many = series.days.length > 14;
  const rows = series.days.map((d, i) => ({
    day: dayTick(d, many), date: d,
    revenue: series.revenue[i], previous: series.prev_revenue[i] ?? 0, bookings: series.bookings[i],
  }));
  const hasData = rows.some(r => r.revenue || r.previous);
  return (
    <Panel title="Revenue & bookings" meta={`${rangeLabel} vs previous`} className="lg:col-span-3">
      {!hasData ? <Empty text="No bookings checking in during this period." /> : (
        <>
          <div className="h-60">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={rows} margin={{ top: 8, right: 4, left: 0, bottom: 0 }} barGap={3}>
                <CartesianGrid vertical={false} stroke="var(--haip-border)" />
                <XAxis dataKey="day" tick={{ fontSize: 11, fill: "var(--haip-fg-subtle)" }} tickLine={false} axisLine={false} />
                <YAxis tickFormatter={v => formatRupees(Number(v))} tick={{ fontSize: 10, fill: "var(--haip-fg-subtle)" }} tickLine={false} axisLine={false} width={48} />
                <Tooltip
                  cursor={{ fill: "color-mix(in srgb, var(--primary) 6%, transparent)" }}
                  contentStyle={{ background: "var(--haip-card)", border: "1px solid var(--haip-border)", borderRadius: 8, fontSize: 12 }}
                  labelFormatter={(_, p) => (p?.[0]?.payload?.date ? new Date(`${p[0].payload.date}T00:00:00`).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" }) : "")}
                  formatter={(v, name, item) => name === "This period"
                    ? [`${formatRupees(Number(v))} · ${item?.payload?.bookings ?? 0} booking(s)`, name]
                    : [formatRupees(Number(v)), name]}
                />
                <Bar dataKey="previous" name="Previous" fill="#CBD5D1" radius={[3, 3, 0, 0]} maxBarSize={28} />
                <Bar dataKey="revenue" name="This period" fill="#0F766E" radius={[3, 3, 0, 0]} maxBarSize={28} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="flex gap-5 mt-2 text-xs" style={{ color: "var(--haip-fg-muted)" }}>
            <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm bg-teal-700" />This period</span>
            <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm" style={{ background: "#CBD5D1" }} />Previous period</span>
            <span className="ml-auto tabular-nums">{series.bookings.reduce((a, b) => a + b, 0)} bookings</span>
          </div>
        </>
      )}
    </Panel>
  );
}

// ── Lead funnel ───────────────────────────────────────────────────────────────

const FUNNEL_COLORS = ["bg-blue-600", "bg-teal-700", "bg-emerald-600", "bg-violet-600", "bg-amber-600", "bg-rose-600"];

export function LeadFunnel({ data, rangeLabel }: { data: OverviewResponse; rangeLabel: string }) {
  const total = data.kpi.total_leads;
  const rows = [{ stage: "Enquiries", count: total, color: "bg-slate-700" },
    ...data.funnel.map((f, i) => ({ stage: f.stage, count: f.count, color: FUNNEL_COLORS[i % FUNNEL_COLORS.length] }))];
  return (
    <Panel title="Lead funnel" meta={rangeLabel} className="lg:col-span-2">
      {!total ? <Empty text="No leads in this period." /> : (
        <div className="space-y-4">
          {rows.map((r, i) => (
            <div key={r.stage}>
              <div className="flex items-baseline justify-between text-sm mb-1.5">
                <span style={{ color: "var(--haip-fg)" }}>
                  {r.stage}
                  {i > 0 && <span className="text-[11px] ml-2" style={{ color: "var(--haip-fg-subtle)" }}>{Math.round((100 * r.count) / total)}% of enquiries</span>}
                </span>
                <span className="font-bold tabular-nums" style={{ color: "var(--haip-fg)" }}>{r.count}</span>
              </div>
              <div className="h-2.5 rounded-full" style={{ background: "var(--muted)" }}>
                <div className={cn("h-full rounded-full", r.color)} style={{ width: `${Math.max(2, (100 * r.count) / total)}%` }} />
              </div>
            </div>
          ))}
          <p className="text-[11px]" style={{ color: "var(--haip-fg-subtle)" }}>Only real-lead stages are shown — triage stages are excluded.</p>
        </div>
      )}
    </Panel>
  );
}

// ── Team ──────────────────────────────────────────────────────────────────────

export function TeamTable({ agents, rangeLabel }: { agents: AgentRow[]; rangeLabel: string }) {
  const rows = [...agents].sort((a, b) => b.leads_handled - a.leads_handled);
  return (
    <Panel title="Team" meta={rangeLabel} className="lg:col-span-3">
      {rows.length === 0 ? <Empty text="No active agents." /> : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm min-w-[480px]">
            <thead>
              <tr className="text-[11px] uppercase tracking-wider" style={{ color: "var(--haip-fg-subtle)" }}>
                <th className="text-left font-semibold pb-2">Agent</th>
                <th className="text-right font-semibold pb-2">Leads</th>
                <th className="text-right font-semibold pb-2">First reply</th>
                <th className="text-right font-semibold pb-2">Calls</th>
                <th className="text-right font-semibold pb-2">Booked</th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {rows.map(a => (
                <tr key={a.agent_id} style={{ borderTop: "1px solid var(--haip-border)" }}>
                  <td className="py-2.5">
                    <span className="flex items-center gap-2.5 min-w-0">
                      <span className="w-7 h-7 rounded-full flex-shrink-0 flex items-center justify-center text-xs font-bold bg-teal-50 text-teal-800 dark:bg-teal-950 dark:text-teal-200">
                        {a.agent_name?.[0]?.toUpperCase() ?? "?"}
                      </span>
                      <span className="font-semibold truncate" style={{ color: "var(--haip-fg)" }}>{a.agent_name}</span>
                    </span>
                  </td>
                  <td className="text-right">{a.leads_handled}</td>
                  <td className="text-right">{a.response_count ? formatSeconds(a.avg_response_seconds) : "—"}</td>
                  <td className="text-right">
                    {a.calls_answered}
                    {a.calls_missed > 0 && <span className="text-red-600 text-xs"> · {a.calls_missed} missed</span>}
                  </td>
                  <td className="text-right font-bold text-violet-700 dark:text-violet-300">{a.conversions}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

// ── Sources ───────────────────────────────────────────────────────────────────

const SOURCE_CHANNEL: Record<string, GuestChannel> = {
  instagram: "instagram", whatsapp: "whatsapp", call: "call",
};

export function LeadSources({ sources, rangeLabel, className }: { sources: OverviewResponse["sources"]; rangeLabel: string; className?: string }) {
  return (
    <Panel title="Where leads come from" meta={rangeLabel} className={cn("lg:col-span-2", className)}>
      {sources.length === 0 ? <Empty text="No leads in this period." /> : (
        <div className="space-y-3.5">
          {sources.map(s => (
            <div key={s.key}>
              <div className="flex items-center justify-between text-sm mb-1.5">
                <span className="flex items-center gap-2" style={{ color: "var(--haip-fg)" }}>
                  {SOURCE_CHANNEL[s.key]
                    ? <ChannelBadge channel={SOURCE_CHANNEL[s.key]} size={18} />
                    : <span className="w-[18px] h-[18px] rounded-full" style={{ background: "var(--muted)" }} />}
                  {s.label}
                  <span className="text-[11px]" style={{ color: "var(--haip-fg-subtle)" }}>{s.count}</span>
                </span>
                <span className="font-bold tabular-nums" style={{ color: "var(--haip-fg)" }}>{s.pct}%</span>
              </div>
              <div className="h-1.5 rounded-full ml-[26px]" style={{ background: "var(--muted)" }}>
                <div className="h-full rounded-full bg-teal-700" style={{ width: `${Math.max(2, s.pct)}%` }} />
              </div>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}

// ── What the AI noticed ───────────────────────────────────────────────────────

const SEVERITY: Record<string, { label: string; dot: string; text: string }> = {
  critical: { label: "Act now", dot: "bg-red-600", text: "text-red-700" },
  high: { label: "Act now", dot: "bg-red-600", text: "text-red-700" },
  medium: { label: "Worth a look", dot: "bg-amber-600", text: "text-amber-700" },
  low: { label: "Good to know", dot: "bg-teal-600", text: "text-teal-700" },
  info: { label: "Good to know", dot: "bg-gray-500", text: "text-gray-600" },
};

export function AiNoticed({ insights, onDismiss, dismissing }: { insights: Insight[]; onDismiss: (id: string) => void; dismissing?: string | null }) {
  if (insights.length === 0) return null;
  return (
    <section>
      <h2 className="text-base font-bold mb-2.5" style={{ color: "var(--haip-fg)" }}>What the AI noticed</h2>
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
        {insights.slice(0, 3).map(i => {
          const sev = SEVERITY[i.severity] ?? SEVERITY.info;
          return (
            <article key={i.id} className="haip-card p-4 flex flex-col gap-1.5">
              <span className={cn("flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider", sev.text)}>
                <span className={cn("w-2 h-2 rounded-full", sev.dot)} />{sev.label}
              </span>
              <h3 className="text-sm font-bold" style={{ color: "var(--haip-fg)" }}>{i.title}</h3>
              <p className="text-[13px] leading-relaxed line-clamp-3" style={{ color: "var(--haip-fg-muted)" }}>{i.body}</p>
              <div className="flex items-center gap-4 mt-auto pt-2 text-xs font-semibold">
                {i.cta_href && i.cta_label && <Link href={i.cta_href} className="text-teal-700 hover:underline">{i.cta_label}</Link>}
                <button type="button" onClick={() => onDismiss(i.id)} disabled={dismissing === i.id}
                  className="hover:underline disabled:opacity-50" style={{ color: "var(--haip-fg-subtle)" }}>
                  Dismiss
                </button>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
