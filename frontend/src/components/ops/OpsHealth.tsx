"use client";

import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { formatINR } from "@/lib/utils";
import { Card, EmptyState, Stat } from "@/components/ui/kit";

/** GET /ops/files/metrics (backend ops_metrics, catalogue D-33 .. D-40). Every figure null = "No data". */
type Times = { count: number; median_min: number | null; p90_min: number | null };
type Rate = { judged: number; pct: number | null };
export type OpsMetrics = {
  period: { from: string; to: string; days: number; label: string };
  time_to_acknowledge: { all: Times; not_acknowledged: number };
  time_to_resolve: { all: Times; closed_without_guest_answer: number };
  issues: { issues: number; stays: number; per_10_stays: number | null;
    repeats: { property: string; label: string; times: number }[] };
  ready_on_time: Rate & { on_time: number };
  paperwork_before_arrival: Rate & { complete: number };
  addon_revenue: { live: boolean; per_stay: number | null };
  reviews: { available: boolean; note: string };
  in_stay_replies: { turns: number; on_time: number; pct: number | null };
  by_property: { property_id: string; name: string; stays: number; issues_per_10_stays: number | null;
    ready_on_time_pct: number | null }[];
};

const NO_DATA = "No data";

export function fmtMinutes(min: number | null): string {
  if (min == null) return NO_DATA;
  if (min < 60) return `${Math.round(min)} min`;
  if (min < 48 * 60) { const h = Math.floor(min / 60), m = Math.round(min % 60); return m ? `${h} h ${m} min` : `${h} h`; }
  return `${Math.round(min / 1440)} days`;
}

export const fmtPct = (pct: number | null) => (pct == null ? NO_DATA : `${Math.round(pct)}%`);

/** Nothing at all to judge in the period: one empty state instead of seven "No data" cards. */
export const isEmpty = (m: OpsMetrics) =>
  m.issues.stays === 0 && m.time_to_acknowledge.all.count === 0 && m.time_to_resolve.all.count === 0 && m.in_stay_replies.turns === 0;

/** "How operations are doing" on Ops Today, owner/manager only (the caller decides). Compact: Stat cards + one note. */
export function OpsHealth() {
  const { data: m, isPending, isError, refetch } = useQuery<OpsMetrics>({
    queryKey: ["ops-metrics", 30],
    queryFn: () => api.get("/ops/files/metrics", { params: { days: 30 } }).then(r => r.data),
    staleTime: 5 * 60_000,
  });
  const period = m ? `${m.period.label.toLowerCase()}` : "last 30 days";

  return (
    <section aria-labelledby="ops-health-h" className="flex flex-col gap-2">
      <h2 id="ops-health-h" className="text-[13px] font-bold uppercase tracking-[0.08em] text-[var(--haip-fg-subtle)]">
        How operations are doing <span className="font-medium normal-case tracking-normal">· {period}, IST</span>
      </h2>
      {isError ? (
        <Card>
          <EmptyState title="Couldn't load these numbers" hint="Check your connection, then try again."
            action={<button type="button" className="haip-btn-secondary min-h-11" onClick={() => refetch()}>Try again</button>} />
        </Card>
      ) : !isPending && m && isEmpty(m) ? (
        <Card><EmptyState title={`No stays or issues in the ${period} yet`} hint="These numbers fill in as guests check in and the team handles issues." /></Card>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-4">
            <Stat loading={isPending} label="Time to acknowledge" value={fmtMinutes(m?.time_to_acknowledge.all.median_min ?? null)}
              hint={m?.time_to_acknowledge.all.p90_min != null ? `median · 9 in 10 within ${fmtMinutes(m.time_to_acknowledge.all.p90_min)}` : period} />
            <Stat loading={isPending} label="Time to fix" value={fmtMinutes(m?.time_to_resolve.all.median_min ?? null)}
              hint={m?.time_to_resolve.all.count ? `median of ${m.time_to_resolve.all.count} fixed` : period} />
            <Stat loading={isPending} label="Issues per 10 stays" value={m?.issues.per_10_stays ?? NO_DATA}
              hint={m ? `${m.issues.issues} issues · ${m.issues.stays} stays` : period} />
            <Stat loading={isPending} label="Ready on time" value={fmtPct(m?.ready_on_time.pct ?? null)}
              hint={m?.ready_on_time.judged ? `${m.ready_on_time.on_time} of ${m.ready_on_time.judged} stays` : period} />
            <Stat loading={isPending} label="Paperwork done" value={fmtPct(m?.paperwork_before_arrival.pct ?? null)}
              hint={m?.paperwork_before_arrival.judged ? `form + paid before arrival · ${m.paperwork_before_arrival.complete} of ${m.paperwork_before_arrival.judged}` : period} />
            <Stat loading={isPending} label="Add-ons per stay" value={m?.addon_revenue.per_stay != null ? formatINR(m.addon_revenue.per_stay) : NO_DATA}
              hint={m && !m.addon_revenue.live ? "no add-ons sold yet" : "paid add-ons"} />
            <Stat loading={isPending} label="In-stay replies on time" value={fmtPct(m?.in_stay_replies.pct ?? null)}
              hint={m?.in_stay_replies.turns ? `${m.in_stay_replies.on_time} of ${m.in_stay_replies.turns} guest messages` : period} />
          </div>
          {m && (m.issues.repeats.length > 0 || m.by_property.length > 1) && (
            <details className="haip-card px-4 py-3 text-[14px]">
              <summary className="min-h-11 cursor-pointer content-center font-semibold text-[var(--haip-fg)]">By unit</summary>
              <ul className="mt-1 flex flex-col divide-y divide-[var(--haip-border)]">
                {m.by_property.map(p => (
                  <li key={p.property_id} className="flex flex-wrap justify-between gap-x-3 py-2">
                    <span className="font-medium">{p.name}</span>
                    <span className="text-[var(--haip-fg-muted)]">
                      {p.issues_per_10_stays ?? NO_DATA} issues / 10 stays · ready {fmtPct(p.ready_on_time_pct)}
                    </span>
                  </li>
                ))}
              </ul>
              {m.issues.repeats.map(r => (
                <p key={`${r.property}-${r.label}`} className="mt-2 text-[var(--haip-fg-muted)]">
                  {r.label} failed {r.times} times on {r.property}
                </p>
              ))}
            </details>
          )}
          {m && !m.reviews.available && <p className="text-[12.5px] text-[var(--haip-fg-subtle)]">Review rate: {m.reviews.note}</p>}
        </>
      )}
    </section>
  );
}
