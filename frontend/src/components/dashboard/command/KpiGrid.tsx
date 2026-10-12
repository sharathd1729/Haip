"use client";
// The compact top of the page: six headline numbers in one hairline lattice (two columns on a phone, three on a
// tablet, six on a wide screen). Every tile opens the records behind it. A figure the viewer may not read says
// "Restricted"; it is never shown as zero.
import type { ReactNode } from "react";
import Link from "next/link";
import { Lock } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { ChangePill } from "./parts";
import { inr, isRestricted, num, pct, type BusinessOverview, type Change } from "./types";

function Tile({ label, value, hint, change, href, restricted }: {
  label: string; value: ReactNode; hint?: ReactNode; change?: Change | null; href: string; restricted?: boolean;
}) {
  return (
    <Link href={href} aria-label={restricted ? `${label}: restricted for your role` : undefined}
      className="flex min-h-[5.75rem] min-w-0 flex-col justify-between gap-1 bg-[var(--haip-card)] px-3.5 py-3 transition-colors hover:bg-[var(--haip-surface)] focus-visible:relative focus-visible:z-10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 sm:px-4">
      <span className="text-[12px] font-medium leading-tight text-[var(--haip-fg-subtle)]">{label}</span>
      <span className={cn("flex items-center gap-1.5 font-[family-name:var(--font-display)] font-semibold leading-none tracking-tight tabular-nums text-[var(--haip-fg)] [overflow-wrap:anywhere]",
        restricted ? "text-[15px] text-[var(--haip-fg-subtle)]" : "text-[clamp(1.2rem,5.8vw,1.65rem)]")}>
        {restricted && <Lock size={14} aria-hidden />}{value}
      </span>
      <span className="flex min-h-4 flex-wrap items-center gap-x-1.5 text-[11.5px] leading-tight text-[var(--haip-fg-subtle)]">
        {change && <ChangePill change={change} className="text-[11.5px]" />}
        {hint}
      </span>
    </Link>
  );
}

export function KpiGrid({ data }: { data: BusinessOverview }) {
  const { leads, bookings, revenue, attention } = data;
  const alerts = attention.reduce((a, i) => a + i.count, 0) + data.stale_integrations.length;
  const bookingsOff = isRestricted(bookings), revenueOff = isRestricted(revenue);
  return (
    <section aria-label="Headline numbers" className="grid grid-cols-2 gap-px overflow-hidden rounded-[var(--radius)] border border-[var(--haip-border)] bg-[var(--haip-border)] md:grid-cols-3 xl:grid-cols-6">
      <Tile label="Leads received" value={num(leads.received)} change={leads.received_change} href="/dashboard/leads" hint="spam left out" />
      <Tile label="Bookings made" value={bookingsOff ? "Restricted" : num(bookings.confirmed_created)} restricted={bookingsOff}
        change={bookingsOff ? null : bookings.confirmed_change} href="/dashboard/bookings" hint={bookingsOff ? undefined : `${num(bookings.cancelled_of_created)} cancelled`} />
      <Tile label="Booked value" value={revenueOff ? "Restricted" : inr(revenue.gross_booking_value)} restricted={revenueOff}
        change={revenueOff ? null : revenue.gross_change} href="/dashboard/targets" hint={revenueOff ? undefined : "stay charge"} />
      <Tile label="Cash collected" value={revenueOff ? "Restricted" : inr(revenue.collected)} restricted={revenueOff}
        change={revenueOff ? null : revenue.collected_change} href="/dashboard/bookings" hint={revenueOff ? undefined : `${inr(revenue.refunds)} refunded`} />
      <Tile label="Lead to booking" value={pct(leads.conversion_rate)} href="/dashboard/leads" hint={`${num(leads.converted_to_booking)} of ${num(leads.received)} so far`} />
      <Tile label="Needs attention" value={num(alerts)} href="#needs-attention" hint={alerts ? "see the list below" : "all clear"} />
    </section>
  );
}
