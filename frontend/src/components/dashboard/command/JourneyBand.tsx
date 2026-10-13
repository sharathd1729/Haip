"use client";
// Lead identified -> Qualified -> Booked -> Payment collected, as one band. Bar length is the stage count relative to the
// leads identified; the figure between two stages is the share of its stated base that reached it. A LEAD is a person with a
// phone number, counted once. It is a COHORT (people who became leads in the period, followed so far), and the page says so.
import Link from "next/link";
import { Info } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { ChangePill, SectionTitle } from "./parts";
import { isRestricted, num, pct, type BusinessOverview, type FunnelStage } from "./types";

const LINKS: Record<FunnelStage["key"], string> = {
  identified: "/dashboard/leads", qualified: "/dashboard/leads", booked: "/dashboard/bookings", paid: "/dashboard/bookings",
};
const SHADE = ["bg-primary", "bg-primary/80", "bg-primary/60", "bg-primary/45"];

export function JourneyBand({ data }: { data: BusinessOverview }) {
  const { stages, note } = data.funnel;
  const top = Math.max(1, stages[0]?.count ?? 0);
  const bookingsHidden = isRestricted(data.bookings);
  const empty = stages.every(s => s.count === 0);
  const split = !isRestricted(data.bookings) ? data.bookings.by_lead_cohort : null;
  const noNumber = !isRestricted(data.bookings) ? data.bookings.no_identified_lead : null;

  return (
    <section aria-labelledby="journey-title" className="haip-card px-5 py-5 sm:px-6">
      <SectionTitle sub="People who became leads in this period (phone number captured), and what became of them so far">
        <span id="journey-title">From lead to payment</span>
      </SectionTitle>

      {empty ? (
        <p className="py-6 text-center text-[13px] text-[var(--haip-fg-subtle)]">No one became a lead in this period, so there is no journey to show.</p>
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
                    {hidden ? "restricted" : s.rate_from_previous == null ? "no rate yet" : `${pct(s.rate_from_previous)} of ${(s.key === "paid" ? stages[2] : stages[0]).label.toLowerCase()}`}
                  </p>
                )}
                {i === 0 && <p className="mb-1 text-[11.5px] text-[var(--haip-fg-subtle)]">&nbsp;</p>}
                <Link href={LINKS[s.key]} className="group block rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40">
                  {/* From the tablet width the four stages sit side by side: the label reserves two lines so the counts share a baseline. */}
                  <span className="block text-[13px] font-medium leading-5 text-[var(--haip-fg-2)] group-hover:text-[var(--haip-fg)] sm:min-h-10 lg:min-h-0">{s.label}</span>
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
          {split && (split.from_earlier_leads.count ?? 0) + (split.from_new_leads.count ?? 0) > 0 && (
            <p>Bookings made in this period: <span className="font-semibold text-[var(--haip-fg-2)]">{num(split.from_new_leads.count)}</span> from people who became leads in it,{" "}
              <span className="font-semibold text-[var(--haip-fg-2)]">{num(split.from_earlier_leads.count)}</span> from leads identified earlier. Only the first group is in the journey above.</p>
          )}
          {noNumber != null && noNumber > 0 && (
            <p><span className="font-semibold text-[var(--haip-fg-2)]">{num(noNumber)} booking{noNumber === 1 ? "" : "s"} made in this period {noNumber === 1 ? "is" : "are"} from a guest with no phone number on file</span>, so {noNumber === 1 ? "it is" : "they are"} not a lead.</p>
          )}
        </div>
      </div>
    </section>
  );
}
