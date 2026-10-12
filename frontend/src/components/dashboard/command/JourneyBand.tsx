"use client";
// Lead received -> Valid -> Booking confirmed -> Payment collected, as one band. Bar length is the stage count
// relative to leads received; the figure between two stages is the share of the previous stage that reached the next.
// It is a COHORT (leads received in the period, followed so far), and the page says so.
import Link from "next/link";
import { Info } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { ChangePill, SectionTitle } from "./parts";
import { isRestricted, num, pct, type BusinessOverview, type FunnelStage } from "./types";

const LINKS: Record<FunnelStage["key"], string> = {
  received: "/dashboard/leads", valid: "/dashboard/leads", booked: "/dashboard/bookings", paid: "/dashboard/bookings",
};
const SHADE = ["bg-primary", "bg-primary/80", "bg-primary/60", "bg-primary/45"];

export function JourneyBand({ data }: { data: BusinessOverview }) {
  const { stages, note } = data.funnel;
  const top = Math.max(1, stages[0]?.count ?? 0);
  const bookingsHidden = isRestricted(data.bookings);
  const empty = stages.every(s => s.count === 0);
  const unlinked = !isRestricted(data.bookings) ? data.bookings.not_linked_to_a_lead : null;

  return (
    <section aria-labelledby="journey-title" className="haip-card px-5 py-5 sm:px-6">
      <SectionTitle sub="Leads received in this period, and what became of them so far">
        <span id="journey-title">From lead to payment</span>
      </SectionTitle>

      {empty ? (
        <p className="py-6 text-center text-[13px] text-[var(--haip-fg-subtle)]">No leads were received in this period, so there is no journey to show.</p>
      ) : (
        <ol className="grid grid-cols-1 gap-x-2 gap-y-4 sm:grid-cols-4">
          {stages.map((s, i) => {
            const hidden = bookingsHidden && (s.key === "booked" || s.key === "paid");
            const width = hidden ? 0 : Math.max(s.count ? 4 : 0, Math.round((s.count / top) * 100));
            return (
              <li key={s.key} className="min-w-0">
                {i > 0 && (
                  <p className="mb-1 flex items-center gap-1 text-[11.5px] tabular-nums text-[var(--haip-fg-subtle)]">
                    <span aria-hidden>↳</span>
                    {hidden ? "restricted" : s.rate_from_previous == null ? "no rate yet" : `${pct(s.rate_from_previous)} of ${stages[i - 1].label.toLowerCase()}`}
                  </p>
                )}
                {i === 0 && <p className="mb-1 text-[11.5px] text-[var(--haip-fg-subtle)]">&nbsp;</p>}
                <Link href={LINKS[s.key]} className="group block rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40">
                  {/* The label reserves two lines below the desktop width so the four counts stay on one baseline. */}
                  <span className="block min-h-10 text-[13px] font-medium leading-5 text-[var(--haip-fg-2)] group-hover:text-[var(--haip-fg)] lg:min-h-0">{s.label}</span>
                  <span className="mt-0.5 flex items-baseline justify-between gap-2">
                    <span className="font-[family-name:var(--font-display)] text-[28px] font-semibold leading-tight tabular-nums text-[var(--haip-fg)]">
                      {hidden ? "—" : num(s.count)}
                    </span>
                    <ChangePill change={hidden ? null : s.change} />
                  </span>
                  <span className="mt-2 block h-2.5 overflow-hidden rounded-sm bg-[var(--haip-surface)]" aria-hidden>
                    <span className={cn("block h-full rounded-sm motion-safe:transition-[width] motion-safe:duration-300 motion-safe:ease-[cubic-bezier(0.23,1,0.32,1)]", SHADE[i])} style={{ width: `${width}%` }} />
                  </span>
                </Link>
              </li>
            );
          })}
        </ol>
      )}

      <div className="mt-4 flex items-start gap-2 border-t border-[var(--haip-border)] pt-3 text-[12px] leading-relaxed text-[var(--haip-fg-subtle)]">
        <Info size={14} className="mt-0.5 shrink-0" aria-hidden />
        <div className="space-y-0.5">
          <p>{note}</p>
          {unlinked != null && unlinked > 0 && (
            <p><span className="font-semibold text-[var(--haip-fg-2)]">{num(unlinked)} booking{unlinked === 1 ? "" : "s"} made in this period {unlinked === 1 ? "has" : "have"} no lead attached</span> and {unlinked === 1 ? "is" : "are"} not in this journey.</p>
          )}
        </div>
      </div>
    </section>
  );
}
