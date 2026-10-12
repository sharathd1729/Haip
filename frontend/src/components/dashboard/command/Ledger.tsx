"use client";
// The three business columns — Leads, Bookings, Revenue — as ONE surface divided by hairlines (not three cards,
// not cards inside cards). Each column leads with its headline number, then plain label/value lines.
import type { ReactNode } from "react";
import Link from "next/link";
import { CalendarCheck, ChevronRight, IndianRupee, Users } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { ChangePill, NotAvailable, RestrictedNote, Row } from "./parts";
import { inr, isRestricted, isUnavailable, num, pct, type BusinessOverview } from "./types";

function Column({ title, icon, headline, headlineLabel, change, children, href, hrefLabel }: {
  title: string; icon: ReactNode; headline: ReactNode; headlineLabel: string; change?: ReactNode;
  children: ReactNode; href?: string; hrefLabel?: string;
}) {
  return (
    <section aria-labelledby={`ledger-${title}`} className="flex min-w-0 flex-col px-5 py-5 sm:px-6">
      <div className="flex items-center gap-2 text-[var(--haip-fg-2)]">
        <span className="text-[var(--haip-icon-neutral)]" aria-hidden>{icon}</span>
        <h2 id={`ledger-${title}`} className="text-[13px] font-semibold uppercase tracking-wide">{title}</h2>
      </div>
      <p className="mt-3 break-words font-[family-name:var(--font-display)] text-[34px] font-semibold leading-none tracking-tight text-[var(--haip-fg)] tabular-nums">
        {headline}
      </p>
      <p className="mt-1.5 flex flex-wrap items-center gap-x-2 text-xs text-[var(--haip-fg-subtle)]">
        <span>{headlineLabel}</span>{change}
      </p>
      <dl className="mt-4 divide-y divide-[var(--haip-border)] border-t border-[var(--haip-border)] [&>*]:first:pt-2">{children}</dl>
      {href && (
        <Link href={href} className="mt-auto inline-flex items-center gap-0.5 self-start pt-4 text-[12.5px] font-semibold text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 rounded">
          {hrefLabel}<ChevronRight size={14} aria-hidden />
        </Link>
      )}
    </section>
  );
}

export function Ledger({ data }: { data: BusinessOverview }) {
  const { leads, bookings, revenue } = data;
  const week = !isRestricted(bookings) ? bookings.upcoming_window_days : 7;

  return (
    <div className="haip-card grid grid-cols-1 divide-y divide-[var(--haip-border)] md:grid-cols-3 md:divide-x md:divide-y-0">
      <Column title="Leads" icon={<Users size={16} />} headline={num(leads.received)} headlineLabel="received"
        change={<ChangePill change={leads.received_change} />} href="/dashboard/leads" hrefLabel="Open Leads360">
        <Row label="Valid" value={num(leads.valid)} hint="in a pipeline stage that counts as a real lead" />
        <Row label="Invalid (triage)" value={num(leads.invalid)} />
        <Row label="Converted to a booking" value={num(leads.converted_to_booking)}
          hint={leads.conversion_rate == null ? "no leads in this period" : `${pct(leads.conversion_rate)} of received, so far`} />
        <Row label="Unassigned right now" value={num(leads.unassigned_now)} tone={leads.unassigned_now > 0 ? "warning" : undefined}
          hint="open leads nobody owns, not limited to this period" href="/dashboard/my-day?kind=unassigned" />
        <Row label="Marked as spam, left out" value={num(leads.marked_spam_excluded)} muted />
      </Column>

      {isRestricted(bookings) ? (
        <Column title="Bookings" icon={<CalendarCheck size={16} />} headline="—" headlineLabel="restricted">
          <div className="pt-3"><RestrictedNote what="Booking figures" permission="bookings.read" /></div>
        </Column>
      ) : (
        <Column title="Bookings" icon={<CalendarCheck size={16} />} headline={num(bookings.confirmed_created)} headlineLabel="made in this period"
          change={<ChangePill change={bookings.confirmed_change} />} href="/dashboard/bookings" hrefLabel="Open Bookings">
          <Row label="Cancelled" value={num(bookings.cancelled_of_created)} hint="of those made in this period" />
          <Row label={`Check-ins, next ${week} days`} value={num(bookings.upcoming_checkins)} href="/dashboard/bookings?quick=upcoming" />
          <Row label="Still owing money" value={num(bookings.needs_payment)}
            hint={bookings.payment_overdue > 0 ? `${num(bookings.payment_overdue)} past a due date` : "confirmed or in house, not fully paid"}
            tone={bookings.payment_overdue > 0 ? "danger" : undefined} href="/dashboard/bookings?quick=due" />
          <Row label="Pending" value="Not tracked" muted hint="HAIP has no pending booking status" />
          {bookings.not_linked_to_a_lead != null && (
            <Row label="Not linked to a lead" value={num(bookings.not_linked_to_a_lead)} muted hint="cannot be traced to a source or agent" />
          )}
        </Column>
      )}

      {isRestricted(revenue) ? (
        <Column title="Revenue" icon={<IndianRupee size={16} />} headline="—" headlineLabel="restricted">
          <div className="pt-3"><RestrictedNote what="Revenue figures" permission="revenue.read" /></div>
        </Column>
      ) : (
        <Column title="Revenue" icon={<IndianRupee size={16} />} headline={inr(revenue.gross_booking_value)} headlineLabel="booked in this period (stay charge)"
          change={<ChangePill change={revenue.gross_change} />} href="/dashboard/targets" hrefLabel="Open Targets">
          <Row label="Collected" value={inr(revenue.collected)} hint="by payment date" />
          <Row label="Refunded" value={inr(revenue.refunds)} />
          <Row label="Net cash received" value={inr(revenue.net_collected)} hint="collected less refunds" />
          <Row label="Still to collect" value={inr(revenue.outstanding_on_live_bookings)} hint="live bookings, all dates"
            tone={(revenue.overdue_amount ?? 0) > 0 ? "danger" : undefined} />
          {(revenue.overdue_amount ?? 0) > 0 && <Row label="…of which overdue" value={inr(revenue.overdue_amount)} tone="danger" />}
          <Row label="Add-ons on these bookings" value={inr(revenue.add_ons_value)} muted />
          <Row label="Guests arriving in this period" value={inr(revenue.arriving_value)} muted hint="a different measure from booked value" />
          <TargetLine target={revenue.target} />
          {isUnavailable(revenue.net_revenue) && <NotAvailable label="Net revenue" reason={revenue.net_revenue.reason} />}
        </Column>
      )}
    </div>
  );
}

function TargetLine({ target }: { target: NonNullable<Extract<BusinessOverview["revenue"], { restricted: false }>["target"]> | null }) {
  if (!target) return null;
  if (isUnavailable(target)) return <NotAvailable label="Target" reason={target.reason} />;
  const done = target.achieved_pct ?? 0;
  return (
    <div className="py-2.5">
      <div className="flex items-baseline justify-between gap-3 text-[13px]">
        <span className="text-[var(--haip-fg-2)]">Month target</span>
        <span className="font-semibold tabular-nums text-[var(--haip-fg)]">{pct(target.achieved_pct)} of {inr(target.monthly_target)}</span>
      </div>
      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-[var(--haip-surface)]"
        role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.min(100, Math.round(done))} aria-label="Month target achieved">
        <div className={cn("h-full rounded-full bg-primary motion-safe:transition-[width] motion-safe:duration-300 motion-safe:ease-[cubic-bezier(0.23,1,0.32,1)]")} style={{ width: `${Math.min(100, done)}%` }} />
      </div>
      <p className="mt-1 text-[11.5px] text-[var(--haip-fg-subtle)]">{inr(target.picked_up)} picked up so far. Basis: {target.basis}.</p>
    </div>
  );
}
