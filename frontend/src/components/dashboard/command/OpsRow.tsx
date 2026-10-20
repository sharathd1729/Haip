"use client";
// Caravans (per property this month: booked value, nights booked, share of the month), AI and calls (quotes waiting for approval,
// lead-stage suggestions, calls in the period) and the Team table (this month's target vs achieved booked value, calls, leads
// owned, median first reply).
import type { ReactNode } from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { Block, Hidden, Meter, OpenLink } from "./OwnerParts";
import { dayRange, lakh, monthName, restricted, type AiCalls, type Caravans, type Team } from "./owner";
import { duration, type Restricted } from "./types";

export function CaravansCard({ caravans, caravan }: { caravans: Caravans | Restricted; caravan: boolean }) {
  const title = caravan ? "Caravans" : "Properties";
  if (restricted(caravans)) return <Block title={title} period="this month"><Hidden what="Bookings" /></Block>;
  const month = monthName(caravans.month);
  return (
    <Block title={title} period={`${month} · ${caravans.days_in_month} days`}>
      {caravans.items.length === 0 ? (
        <p className="py-6 text-center text-[13px] text-[var(--haip-fg-subtle)]">No {caravan ? "vehicles" : "properties"} set up yet.</p>
      ) : (
        <ul className="grid grid-cols-1 gap-2.5 min-[420px]:grid-cols-2">
          {caravans.items.map(c => (
            <li key={c.property_id} className="min-w-0 rounded-xl bg-[var(--haip-surface)] px-3.5 py-3">
              <p className="truncate text-[14px] font-semibold text-[var(--haip-fg)]">{c.name}</p>
              <p className="mt-1 font-[family-name:var(--font-display)] text-[20px] font-semibold tabular-nums text-[var(--haip-fg)]">
                {c.booked_value == null ? "—" : lakh(c.booked_value)}
              </p>
              <p className="text-[12.5px] tabular-nums text-[var(--haip-fg-subtle)]">{c.nights} night{c.nights === 1 ? "" : "s"} booked · {c.occupancy_pct ?? 0}% of {month}</p>
              <Meter className="mt-2 h-1.5" parts={[{ pct: c.occupancy_pct ?? 0, tone: "primary" }]} label={`${c.occupancy_pct ?? 0}% of the month booked`} />
            </li>
          ))}
        </ul>
      )}
      <p className="mt-3 text-[12px] text-[var(--haip-fg-subtle)]">Value = bookings made this month (rental + add-ons){caravans.items.some(c => c.booked_value == null) ? ", hidden for your role" : ""}. Nights = nights stayed this month, whenever booked.</p>
    </Block>
  );
}

function Mini({ label, value, sub, action }: { label: string; value: number; sub: ReactNode; action?: ReactNode }) {
  return (
    <div className="min-w-0 rounded-xl bg-[var(--haip-surface)] px-3.5 py-3">
      <p className="text-[12.5px] font-medium text-[var(--haip-fg-muted)]">{label}</p>
      <p className="mt-0.5 font-[family-name:var(--font-display)] text-[22px] font-semibold tabular-nums text-[var(--haip-fg)]">{value}</p>
      <div className="text-[12.5px] text-[var(--haip-fg-subtle)]">{sub}</div>
      {action}
    </div>
  );
}

export function AiCallsCard({ data, period }: { data: AiCalls | null; period: string }) {
  if (!data) return null;
  const { sales_actions: sa, autopilot: ap, calls } = data;
  const byStage = ap.by_stage.map(s => `${s.count} ${s.label}`).join(", ");
  return (
    <Block title="AI and calls" period={`waiting now · calls ${period.toLowerCase()}`}>
      <div className="grid grid-cols-1 gap-2.5 min-[420px]:grid-cols-2 xl:grid-cols-3">
        <Mini label="Quotes waiting for approval" value={sa.count} sub={sa.count ? `prepared by the AI sales agent${sa.items[0] ? ` · ${sa.items.map(i => i.name).join(", ")}` : ""}` : "nothing waiting"}
          action={sa.count > 0 ? <OpenLink href={sa.items.length === 1 ? sa.items[0].href : sa.href}>Review</OpenLink> : undefined} />
        <Mini label="Lead stage suggestions" value={ap.count} sub={ap.count ? byStage : "nothing to review"}
          action={ap.count > 0 ? <OpenLink href={ap.items.length === 1 ? ap.items[0].href : ap.href}>Review</OpenLink> : undefined} />
        <Mini label="Calls" value={calls.total}
          sub={calls.missed ? `${calls.missed} missed · ${calls.returned} returned${calls.not_returned ? `, ${calls.not_returned} not yet` : ""}` : "none missed"}
          action={<OpenLink href={calls.href}>Calls</OpenLink>} />
      </div>
    </Block>
  );
}

export function TeamCard({ team }: { team: Team | null }) {
  if (!team) return null;
  const month = monthName(team.month);
  return (
    <Block title="Team" period={`${dayRange(team.from, team.to)} · ${month} targets on booked value`}
      actions={<Link href="/dashboard/targets" className="inline-flex min-h-11 items-center text-[12.5px] font-semibold text-primary hover:underline lg:min-h-0">Targets</Link>}>
      {team.rows.length === 0 ? (
        <p className="py-6 text-center text-[13px] text-[var(--haip-fg-subtle)]">No selling team members yet.</p>
      ) : (
        <>
          <div className="hidden grid-cols-[minmax(0,1.4fr)_repeat(3,minmax(0,1fr))_repeat(3,minmax(0,0.8fr))] gap-x-3 border-b border-[var(--haip-border)] pb-1.5 text-[11.5px] font-semibold text-[var(--haip-fg-subtle)] lg:grid">
            <span>Person</span><span className="text-right">Target</span><span className="text-right">Achieved</span><span /><span className="text-right">Calls</span><span className="text-right">Leads owned</span><span className="text-right">First reply</span>
          </div>
          <ul className="divide-y divide-[var(--haip-border)]">
            {team.rows.map(r => (
              <li key={r.agent_id} className="grid grid-cols-2 gap-x-3 gap-y-1.5 py-3 sm:grid-cols-3 lg:grid-cols-[minmax(0,1.4fr)_repeat(3,minmax(0,1fr))_repeat(3,minmax(0,0.8fr))] lg:items-center lg:py-2.5">
                <span className="col-span-2 truncate text-[14px] font-semibold text-[var(--haip-fg)] sm:col-span-3 lg:col-span-1 lg:text-[13px]">{r.name}</span>
                <Cell label="Target">{r.target == null ? "Not set" : lakh(r.target)}</Cell>
                <Cell label="Achieved">{lakh(r.achieved)}</Cell>
                <span className="col-span-2 flex items-center gap-2 sm:col-span-1">
                  <Meter className="h-1.5" parts={[{ pct: r.achieved_pct ?? 0, tone: "primary" }]} label={`${r.achieved_pct ?? 0}% of target`} />
                  <span className="w-10 shrink-0 text-right text-[12px] tabular-nums text-[var(--haip-fg-subtle)]">{r.achieved_pct == null ? "—" : `${Math.round(r.achieved_pct)}%`}</span>
                </span>
                <Cell label="Calls">{r.calls}</Cell>
                <Cell label="Leads owned">{r.leads_owned}</Cell>
                <Cell label="First reply">{duration(r.median_first_reply_seconds)}</Cell>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-[11.5px] text-[var(--haip-fg-subtle)]">
            Achieved = booked value of bookings made this month, credited to whoever owns the booking’s enquiry{team.unattributed ? `; ${lakh(team.unattributed)} has no owner` : ""}. First reply is the median time to that person’s first reply to a guest.
          </p>
        </>
      )}
    </Block>
  );
}

function Cell({ label, children }: { label: string; children: ReactNode }) {
  return (
    <span className={cn("min-w-0 text-[13px] tabular-nums text-[var(--haip-fg)] lg:text-right")}>
      <span className="block text-[11px] text-[var(--haip-fg-subtle)] lg:hidden">{label}</span>{children}
    </span>
  );
}
