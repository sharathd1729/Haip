"use client";
// The KPI row of the owner dashboard: New leads, Qualified leads (phone + check-in date), Bookings made, Booked value (rental +
// add-ons) and Payment received, each for the selected period and against the equal period before it.
import type { ReactNode } from "react";
import Link from "next/link";
import { Lock } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { Delta } from "./OwnerParts";
import { lakh, restricted, type OwnerKpis as Kpis } from "./owner";

function Tile({ label, value, sub, href, locked, className }: {
  label: string; value: ReactNode; sub: ReactNode; href: string; locked?: boolean; className?: string;
}) {
  return (
    <Link href={href} aria-label={locked ? `${label}: hidden for your role` : undefined}
      className={cn("flex min-h-[6.5rem] min-w-0 flex-col justify-between gap-1.5 bg-[var(--haip-card)] px-3.5 py-3 transition-colors hover:bg-[var(--haip-surface)] focus-visible:relative focus-visible:z-10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 sm:px-4", className)}>
      <span className="text-[12.5px] font-medium leading-tight text-[var(--haip-fg-muted)]">{label}</span>
      <span className={cn("flex items-center gap-1.5 font-[family-name:var(--font-display)] font-semibold leading-none tracking-tight tabular-nums [overflow-wrap:anywhere]",
        locked ? "text-[15px] text-[var(--haip-fg-subtle)]" : "text-[clamp(1.3rem,6vw,1.75rem)] text-[var(--haip-fg)]")}>
        {locked && <Lock size={14} aria-hidden />}{value}
      </span>
      <span className="text-[11.5px] leading-snug text-[var(--haip-fg-subtle)]">{sub}</span>
    </Link>
  );
}

// Five tiles: the last one spans the leftover columns so the lattice never shows an empty cell (2 / 3 / 5 columns).
const LAST = "col-span-2 xl:col-span-1";

export function OwnerKpis({ kpis, period }: { kpis: Kpis; period: string }) {
  const { new_leads: nl, qualified: q, bookings: b, booked_value: bv, payment_received: pr } = kpis;
  return (
    <section aria-label={`Headline numbers, ${period}`}
      className="grid grid-cols-2 gap-px overflow-hidden rounded-[var(--radius)] border border-[var(--haip-border)] bg-[var(--haip-border)] sm:grid-cols-3 xl:grid-cols-5">
      <Tile label="New leads" value={nl.count} href="/dashboard/leads"
        sub={<>shared a phone number · <Delta change={nl.change} previous={nl.previous} /></>} />
      <Tile label="Qualified leads" value={q.count} href="/dashboard/leads"
        sub={<>phone + check-in date{q.rate_of_new != null ? ` · ${q.rate_of_new}% of new` : ""}</>} />
      {restricted(b)
        ? <Tile label="Bookings made" value="Hidden" sub="needs the bookings permission" href="/dashboard/bookings" locked />
        : <Tile label="Bookings made" value={b.count} href="/dashboard/bookings" sub={<Delta change={b.change} previous={b.previous} />} />}
      {restricted(bv)
        ? <Tile label="Booked value" value="Hidden" sub="needs the revenue permission" href="/dashboard/targets" locked />
        : <Tile label="Booked value" value={lakh(bv.total)} href="/dashboard/targets"
            sub={<>rental {lakh(bv.rental)} · add-ons {lakh(bv.add_ons)}</>} />}
      {restricted(pr)
        ? <Tile label="Payment received" value="Hidden" sub="needs the revenue permission" href="/dashboard/bookings" locked className={LAST} />
        : <Tile label="Payment received" value={lakh(pr.amount)} href="/dashboard/bookings" className={LAST}
            sub={<Delta change={pr.change} previous={pr.previous} money />} />}
      <p className="col-span-full bg-[var(--haip-card)] px-3.5 py-1.5 text-[11.5px] text-[var(--haip-fg-subtle)] sm:px-4">{period} · compared with the equal period before it</p>
    </section>
  );
}
