"use client";
// Lead workflows, Report tab (mock-up "B + A", Oct 20): summary numbers, where leads drop off (funnel) and one row per agent.
// Cohort = leads RECEIVED in the period (IST). Backend: GET /workflows/report?preset=&agent_id= (owner/manager);
// definitions in docs/analytics/KPI_METRIC_CATALOGUE.md, "Lead workflows".
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { Loader2 } from "@/lib/icons";
import { Card, CardBody, CardHeader, EmptyState } from "@/components/ui/kit";

interface Agent {
  agent_id: string | null; name: string; leads: number; seen_minutes: number | null; first_call_minutes: number | null;
  first_contact_minutes: number | null; proposal_minutes: number | null; missed_calls: number; missed_calls_returned: number;
  sold: number; lost: number; top_lost_reason: string | null;
}
interface Report {
  from: string; to: string;
  summary: { leads: number; median_first_contact_minutes: number | null; missed_calls: number; missed_calls_returned: number;
    auto_messages: number; auto_messages_replied: number; sold: number };
  funnel: { key: string; label: string; count: number }[];
  biggest_drop: { from: string; to: string; lost: number } | null;
  agents: Agent[];
  lost_reasons: { reason: string; count: number }[];
}

const PERIODS: [string, string][] = [["this_month", "This month"], ["last_month", "Last month"], ["last_7d", "Last 7 days"], ["last_14d", "Last 14 days"]];
const selectCls = "min-h-[44px] rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-2.5 text-[16px] text-[var(--haip-fg)] sm:text-sm";
const dayFmt = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short" });

export function minutesLabel(m: number | null | undefined): string {
  if (m == null) return "—";
  if (m < 60) return `${m} min`;
  if (m < 24 * 60) { const h = Math.floor(m / 60), r = m % 60; return r && h < 6 ? `${h} h ${r} min` : `${Math.round(m / 60)} h`; }
  const d = Math.round(m / (24 * 60));
  return d === 1 ? "1 day" : `${d} days`;
}
const pct = (a: number, b: number) => (b ? `${Math.round((a / b) * 100)}%` : "—");
const reasonLabel = (r: string | null) => (r ? r.replace(/_/g, " ").replace(/^\w/, c => c.toUpperCase()) : "—");

export function ReportTab() {
  const [preset, setPreset] = useState("this_month");
  const [agent, setAgent] = useState("");
  const q = useQuery<Report>({
    queryKey: ["workflows-report", preset, agent],
    queryFn: () => api.get("/workflows/report", { params: { preset, agent_id: agent || undefined } }).then(r => r.data),
  });
  const agentsQ = useQuery<Report>({     // the agent list always comes from the whole team for the period
    queryKey: ["workflows-report", preset, ""], queryFn: () => api.get("/workflows/report", { params: { preset } }).then(r => r.data),
  });
  const r = q.data;
  const top = r ? Math.max(1, ...r.funnel.map(f => f.count)) : 1;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <select id="report-period" aria-label="Period" className={selectCls} value={preset} onChange={e => setPreset(e.target.value)}>
          {PERIODS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <select id="report-agent" aria-label="Team member" className={selectCls} value={agent} onChange={e => setAgent(e.target.value)}>
          <option value="">Whole team</option>
          {(agentsQ.data?.agents ?? []).filter(a => a.agent_id).map(a => <option key={a.agent_id!} value={a.agent_id!}>{a.name}</option>)}
        </select>
        {r && <span className="text-xs text-[var(--haip-fg-subtle)]">Leads received {dayFmt.format(new Date(r.from))} to {dayFmt.format(new Date(r.to))} (IST)</span>}
      </div>

      {q.isPending ? (
        <p className="flex items-center gap-2 text-sm text-[var(--haip-fg-muted)]"><Loader2 size={14} className="animate-spin" /> Loading…</p>
      ) : q.isError || !r ? (
        <p className="text-sm text-[var(--haip-fg-muted)]">Couldn&apos;t load the report. Refresh to try again.</p>
      ) : r.summary.leads === 0 ? (
        <Card><EmptyState title="No leads in this period" hint="Pick another period, or check back once leads come in." /></Card>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {[
              [String(r.summary.leads), "Leads received"],
              [minutesLabel(r.summary.median_first_contact_minutes), "Median time to first contact"],
              [pct(r.summary.missed_calls_returned, r.summary.missed_calls), `Missed calls returned (${r.summary.missed_calls_returned} of ${r.summary.missed_calls})`],
              [pct(r.summary.auto_messages_replied, r.summary.auto_messages), `Replied to automatic WhatsApp (${r.summary.auto_messages_replied} of ${r.summary.auto_messages})`],
            ].map(([v, k]) => (
              <Card key={k} className="p-3">
                <p className="font-[family-name:var(--font-display)] text-[22px] font-semibold tabular-nums text-[var(--haip-fg)]">{v}</p>
                <p className="text-xs text-[var(--haip-fg-muted)]">{k}</p>
              </Card>
            ))}
          </div>

          <Card>
            <CardHeader title="Where leads drop off" description="How many of these leads reached each step." />
            <CardBody className="grid gap-2">
              {r.funnel.map(f => (
                <div key={f.key} className="grid grid-cols-[110px_minmax(0,1fr)_44px] items-center gap-2.5 text-[13.5px] sm:grid-cols-[140px_minmax(0,1fr)_52px]">
                  <span className="text-[var(--haip-fg)]">{f.label}</span>
                  <svg className="h-6 w-full" viewBox="0 0 100 24" preserveAspectRatio="none" aria-hidden>
                    <rect width="100" height="24" rx="4" className="fill-[var(--haip-primary-tint)]" />
                    <rect width={Math.max(f.count ? 1.5 : 0, (f.count / top) * 100)} height="24" rx="4" className="fill-primary" />
                  </svg>
                  <span className="text-right font-semibold tabular-nums text-[var(--haip-fg)]">{f.count}</span>
                </div>
              ))}
              {r.biggest_drop && (
                <p className="mt-1 text-[13px] text-[var(--haip-fg-muted)]">
                  Biggest drop: <strong className="text-[var(--haip-accent-ink,var(--haip-fg))]">{r.biggest_drop.lost} lead{r.biggest_drop.lost === 1 ? "" : "s"}</strong> reached
                  {" "}“{r.biggest_drop.from}” but not “{r.biggest_drop.to}”.
                </p>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="By team member" description="Median time from the lead arriving to each step. Missed calls are the ones on that person's leads." />
            <CardBody>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[760px] text-[13.5px]">
                  <thead>
                    <tr className="text-left text-xs text-[var(--haip-fg-muted)]">
                      {["Team member", "Leads", "Seen", "First call", "First contact", "Proposal", "Missed calls returned", "Sold", "Top lost reason"].map((h, i) => (
                        <th key={h} className={`border-b border-[var(--haip-border)] px-2 py-2 font-semibold ${i > 0 && i < 8 ? "text-right" : ""}`}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="tabular-nums">
                    {r.agents.map(a => (
                      <tr key={a.agent_id ?? "none"} className="border-b border-[var(--haip-border)] last:border-0">
                        <td className="px-2 py-2 font-semibold text-[var(--haip-fg)]">{a.name}</td>
                        <td className="px-2 py-2 text-right">{a.leads}</td>
                        <td className="px-2 py-2 text-right">{minutesLabel(a.seen_minutes)}</td>
                        <td className="px-2 py-2 text-right">{minutesLabel(a.first_call_minutes)}</td>
                        <td className="px-2 py-2 text-right">{minutesLabel(a.first_contact_minutes)}</td>
                        <td className="px-2 py-2 text-right">{minutesLabel(a.proposal_minutes)}</td>
                        <td className="px-2 py-2 text-right">{a.missed_calls ? `${a.missed_calls_returned} of ${a.missed_calls}` : "—"}</td>
                        <td className="px-2 py-2 text-right">{a.sold}</td>
                        <td className="px-2 py-2">{reasonLabel(a.top_lost_reason)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardBody>
          </Card>

          {r.lost_reasons.length > 0 && (
            <Card>
              <CardHeader title="Why leads were lost" description="Reasons given when leads were marked Lost." />
              <CardBody>
                <ul className="divide-y divide-[var(--haip-border)]">
                  {r.lost_reasons.map(l => (
                    <li key={l.reason} className="flex justify-between gap-3 py-2 text-[13.5px]">
                      <span>{l.reason === "not_recorded" ? "No reason recorded" : reasonLabel(l.reason)}</span>
                      <span className="font-semibold tabular-nums">{l.count}</span>
                    </li>
                  ))}
                </ul>
              </CardBody>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
