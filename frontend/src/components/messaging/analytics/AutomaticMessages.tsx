"use client";
// WhatsApp overview, below the campaigns: what HAIP sent on its own in the same period.
//   Team alerts               staff WhatsApp + app notifications (new lead, escalation, consult, call-me-back)
//   Automatic guest messages  the playbooks' WhatsApps to guests (missed call, tried calling, follow-ups)
// Backend: GET /messaging/analytics/automatic?days= (owner/manager; services/wa_automatic_analytics.py).
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { AlertCircle, Bell, CheckCircle2, Eye, Send } from "@/lib/icons";
import { Card, CardBody, CardHeader, EmptyState, Stat } from "@/components/ui/kit";
import { istTime } from "@/components/workflows/ActivityTab";
import { FailureBars } from "./AnalyticsCharts";
import { fmt, pct, type FailureRow, type Totals } from "./analyticsTypes";

interface Person { user_id: string | null; name: string; role: string | null; received: number; whatsapp: number; push: number; failed: number; last_at: string | null }
interface PlaybookRow extends Totals { playbook: string; name: string; skipped: number; waiting: number }
interface Automatic {
  range: { days: number; from: string; to: string };
  team_alerts: {
    whatsapp: Totals & { waiting: number; delivery_tracked: boolean };
    push: { sent: number; failed: number };
    people: Person[];
    failures: FailureRow[];
  };
  guest_messages: {
    totals: Totals & { skipped: number; waiting: number };
    playbooks: PlaybookRow[];
    skip_reasons: { reason: string; count: number }[];
    failures: FailureRow[];
  };
}

const ROLE: Record<string, string> = { owner: "Owner", manager: "Manager", reservations: "Reservations", concierge: "Concierge", foh: "Front desk", marketing: "Marketing" };
const linkCls = "text-xs font-semibold text-primary hover:underline";

function ActivityLink({ show, label }: { show: "team" | "guest"; label: string }) {
  return <Link href={`/dashboard/workflows?show=${show}#activity`} className={linkCls}>{label}</Link>;
}

export function AutomaticMessages({ days }: { days: number }) {
  const q = useQuery<Automatic>({
    queryKey: ["wa-analytics-automatic", days],
    queryFn: () => api.get("/messaging/analytics/automatic", { params: { days } }).then(r => r.data),
    staleTime: 30_000,
    placeholderData: prev => prev,
  });
  const period = `last ${days} days`;

  if (q.isError && !q.data) {
    return (
      <Card><CardBody className="pt-4">
        <p className="text-sm text-[var(--haip-fg-muted)]">Couldn&apos;t load team alerts and automatic messages.{" "}
          <button type="button" onClick={() => q.refetch()} className={linkCls}>Try again</button></p>
      </CardBody></Card>
    );
  }
  const d = q.data;
  const loading = q.isPending;
  const wa = d?.team_alerts.whatsapp;
  const g = d?.guest_messages;
  const noAlerts = !!d && wa!.sent + wa!.failed + wa!.waiting + d.team_alerts.push.sent + d.team_alerts.push.failed === 0;
  const noGuest = !!g && g.totals.sent + g.totals.failed + g.totals.skipped + g.totals.waiting === 0;

  return (
    <>
      <Card>
        <CardHeader icon={Bell} title="Team alerts"
          description={`WhatsApp and app alerts HAIP sent your team about leads, ${period}`}
          actions={<ActivityLink show="team" label="See each alert" />} />
        <CardBody className="space-y-4">
          {noAlerts ? (
            <EmptyState title="No team alerts in this period"
              hint="Alerts go out when the new-lead or escalation workflows are switched on and a lead waits too long." />
          ) : (
            <>
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
                <Stat label="WhatsApp sent" value={wa ? fmt(wa.sent) : "—"} hint={period} icon={Send} loading={loading} />
                <Stat label="Delivered" value={wa ? (wa.delivery_tracked ? fmt(wa.delivered) : "—") : "—"}
                  hint={wa && !wa.delivery_tracked ? "delivery not tracked" : wa ? `${pct(wa.delivery_rate)} of sent` : period} icon={CheckCircle2} loading={loading} />
                <Stat label="Read" value={wa ? (wa.delivery_tracked ? fmt(wa.read) : "—") : "—"}
                  hint={wa && !wa.delivery_tracked ? "delivery not tracked" : wa ? `${pct(wa.read_rate)} of delivered` : period} icon={Eye} loading={loading} />
                <Stat label="WhatsApp failed" value={wa ? fmt(wa.failed) : "—"} hint={period} icon={AlertCircle} loading={loading} />
                <Stat label="App alerts sent" value={d ? fmt(d.team_alerts.push.sent) : "—"} hint={period} icon={Bell} loading={loading} />
              </div>
              {wa && wa.waiting > 0 && <p className="text-xs text-[var(--haip-fg-subtle)]">{fmt(wa.waiting)} held for quiet hours or still sending.</p>}
              {d && d.team_alerts.people.length > 0 && (
                <div>
                  <h4 className="text-sm font-semibold text-[var(--haip-fg)]">Who got them <span className="font-normal text-[var(--haip-fg-subtle)]">· {period}, times IST</span></h4>
                  <ul className="mt-1 divide-y divide-[var(--haip-border)]">
                    {d.team_alerts.people.map(p => (
                      <li key={p.user_id ?? "team"} className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 py-2.5 text-sm">
                        <span className="min-w-0">
                          <span className="font-semibold text-[var(--haip-fg)]">{p.name}</span>
                          {p.role && <span className="text-xs text-[var(--haip-fg-subtle)]"> · {ROLE[p.role] ?? p.role}</span>}
                        </span>
                        <span className="text-xs tabular-nums text-[var(--haip-fg-muted)]">
                          {fmt(p.received)} received ({fmt(p.whatsapp)} WhatsApp, {fmt(p.push)} app)
                          {p.failed > 0 && <span className="font-semibold text-[var(--viz-fail)]"> · {fmt(p.failed)} failed</span>}
                          {" · "}last {p.last_at ? istTime.format(new Date(p.last_at)) : "—"}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {d && <FailureBars failures={d.team_alerts.failures} title="Why team WhatsApps failed"
                subtitle={`Most common reasons, ${period}`} empty="No failed team WhatsApps." />}
            </>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader icon={Send} title="Automatic guest messages"
          description={`WhatsApps the workflows sent guests on their own (missed call, tried calling, follow-ups), ${period}`}
          actions={<ActivityLink show="guest" label="See each message" />} />
        <CardBody className="space-y-4">
          {noGuest ? (
            <EmptyState title="No automatic guest messages in this period"
              hint="They go out when the missed-call, no-answer or follow-up workflows are switched on." />
          ) : (
            <>
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
                <Stat label="Sent" value={g ? fmt(g.totals.sent) : "—"} hint={period} icon={Send} loading={loading} />
                <Stat label="Delivered" value={g ? fmt(g.totals.delivered) : "—"} hint={g ? `${pct(g.totals.delivery_rate)} of sent` : period} icon={CheckCircle2} loading={loading} />
                <Stat label="Read" value={g ? fmt(g.totals.read) : "—"} hint={g ? `${pct(g.totals.read_rate)} of delivered` : period} icon={Eye} loading={loading} />
                <Stat label="Failed" value={g ? fmt(g.totals.failed) : "—"} hint={period} icon={AlertCircle} loading={loading} />
                <Stat label="Skipped" value={g ? fmt(g.totals.skipped) : "—"} hint={period} loading={loading} />
              </div>
              {g && g.playbooks.length > 0 && (
                <ul className="divide-y divide-[var(--haip-border)]">
                  {g.playbooks.map(p => (
                    <li key={p.playbook} className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 py-2.5 text-sm">
                      <span className="font-semibold text-[var(--haip-fg)]">{p.name}</span>
                      <span className="text-xs tabular-nums text-[var(--haip-fg-muted)]">
                        {fmt(p.sent)} sent · {fmt(p.delivered)} delivered · {fmt(p.read)} read · {fmt(p.failed)} failed · {fmt(p.skipped)} skipped
                      </span>
                    </li>
                  ))}
                </ul>
              )}
              {g && g.skip_reasons.length > 0 && (
                <div>
                  <h4 className="text-sm font-semibold text-[var(--haip-fg)]">Why some were skipped <span className="font-normal text-[var(--haip-fg-subtle)]">· {period}</span></h4>
                  <ul className="mt-1 space-y-1 text-xs text-[var(--haip-fg-muted)]">
                    {g.skip_reasons.map(s => <li key={s.reason}><strong className="tabular-nums text-[var(--haip-fg)]">{fmt(s.count)}</strong> · {s.reason}</li>)}
                  </ul>
                </div>
              )}
              {g && <FailureBars failures={g.failures} title="Why guest messages failed"
                subtitle={`Most common reasons, ${period}`} empty="No failed guest messages." />}
            </>
          )}
        </CardBody>
      </Card>
    </>
  );
}
