"use client";
// Home › Ops (workspace redesign Phase 2). GET /dashboard/ops-board (services/dashboard_tabs.py): the next 7 days of
// arrivals with each one's ID form, post-stay review answers; GET /ops/files/metrics (ops_metrics, last 30 days): ready on
// time, paperwork before arrival, issues per 10 stays. Every arrival opens its trip file.
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { Card, CardBody, CardHeader, EmptyState, Stat, StatusPill, type Tone } from "@/components/ui/kit";
import { Skeleton } from "@/components/ui/skeleton";

interface Board {
  arrivals: { days: number; count: number; missing_within_48h: number; id_forms: { submitted: number; waiting: number; not_sent: number };
    items: { guest: string; property: string; check_in: string; days_from_today: number; id_form: "submitted" | "sent" | "none"; file_state: string | null; href: string }[] };
  reviews: { days: number; asked: number; answered: number; rated: number; average: number | null; low: number };
}
interface Metrics {
  period: { label: string };
  ready_on_time: { judged: number; pct: number | null };
  paperwork_before_arrival: { judged: number; pct: number | null };
  issues: { issues: number; stays: number; per_10_stays: number | null };
}

const FORM: Record<string, { label: string; tone: Tone }> = {
  submitted: { label: "ID form done", tone: "success" },
  sent: { label: "ID form sent, not filled", tone: "highlight" },
  none: { label: "ID form not sent", tone: "neutral" },
};
const pct = (v: number | null) => (v == null ? "No data" : `${v}%`);
const when = (d: number, iso: string) => (d === 0 ? "Today" : d === 1 ? "Tomorrow" : new Date(iso).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" }));

export function OpsTab() {
  const board = useQuery<Board>({ queryKey: ["dashboard-ops-board"], queryFn: () => api.get("/dashboard/ops-board").then(r => r.data), staleTime: 60_000 });
  const metrics = useQuery<Metrics>({ queryKey: ["ops-metrics", 30], queryFn: () => api.get("/ops/files/metrics", { params: { days: 30 } }).then(r => r.data), staleTime: 5 * 60_000 });
  if (board.isPending) return <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{[0, 1, 2, 3].map(i => <Skeleton key={i} className="h-28" />)}</div>;
  if (board.isError || !board.data) {
    return <Card><EmptyState title="Ops didn't load" hint="Check your connection and try again."
      action={<button type="button" onClick={() => board.refetch()} className="min-h-11 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground">Try again</button>} /></Card>;
  }
  const { arrivals: a, reviews: rv } = board.data;
  const m = metrics.data;
  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat variant={a.missing_within_48h ? "accent" : "default"} label="ID forms missing" value={`${a.missing_within_48h}`} hint="guests arriving in the next 48 hours" />
        <Stat label="Arrivals" value={`${a.count}`} hint={`next ${a.days} days · ${a.id_forms.submitted} forms done`} />
        <Stat label="Ready on time" value={m ? pct(m.ready_on_time.pct) : "No data"} hint={m ? `${m.ready_on_time.judged} stays, last 30 days` : "last 30 days"} loading={metrics.isPending && !metrics.isError} />
        <Stat label="Guest rating" value={rv.average != null ? `${rv.average} / 5` : "No data"}
          hint={rv.asked ? `${rv.answered} of ${rv.asked} asked replied · ${rv.low} rated 3 or less` : `no review requests in ${rv.days} days`} />
      </div>

      <Card>
        <CardHeader title="Arrivals and ID forms" description={`Next ${a.days} days, soonest first`}
          actions={<Link href="/dashboard/ops" className="text-sm font-semibold text-primary hover:underline">Open Ops</Link>} />
        <CardBody>
          {a.items.length === 0 ? <p className="py-4 text-sm text-[var(--haip-fg-subtle)]">No arrivals in the next {a.days} days.</p> : (
            <ul className="divide-y divide-[var(--haip-border)]">
              {a.items.map(i => (
                <li key={i.href}>
                  <Link href={i.href} className="flex min-h-12 flex-wrap items-center gap-x-4 gap-y-1 py-2.5 hover:bg-[var(--haip-surface)]">
                    <span className="w-24 shrink-0 text-[13px] font-semibold text-[var(--haip-fg-2)]">{when(i.days_from_today, i.check_in)}</span>
                    <span className="min-w-0 flex-1"><span className="block font-semibold text-[var(--haip-fg)]">{i.guest}</span>
                      <span className="block text-[13px] text-[var(--haip-fg-subtle)]">{i.property}{i.file_state ? "" : " · no trip file yet"}</span></span>
                    <StatusPill tone={FORM[i.id_form].tone}>{FORM[i.id_form].label}</StatusPill>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>

      {m && (
        <Card>
          <CardHeader title="How operations went" description={m.period.label} />
          <CardBody>
            <dl className="grid gap-4 sm:grid-cols-3">
              <div><dt className="text-[13px] text-[var(--haip-fg-subtle)]">Paperwork done before arrival</dt><dd className="text-xl font-semibold">{pct(m.paperwork_before_arrival.pct)}</dd></div>
              <div><dt className="text-[13px] text-[var(--haip-fg-subtle)]">Issues per 10 stays</dt><dd className="text-xl font-semibold">{m.issues.per_10_stays ?? "No data"}</dd></div>
              <div><dt className="text-[13px] text-[var(--haip-fg-subtle)]">Issues raised</dt><dd className="text-xl font-semibold">{m.issues.issues} <span className="text-[13px] font-normal text-[var(--haip-fg-subtle)]">across {m.issues.stays} stays</span></dd></div>
            </dl>
          </CardBody>
        </Card>
      )}
    </div>
  );
}
