"use client";
// Bookings made in the period by property and by booking channel (the platform the guest booked on). These are counted
// from the bookings themselves, so they include bookings with no lead attached.
import { Empty } from "./parts";
import { Bar } from "./Acquisition";
import { inr, isRestricted, num, type BusinessOverview } from "./types";

const CHANNEL_LABEL: Record<string, string> = {
  direct: "Direct", airbnb: "Airbnb", "booking.com": "Booking.com", booking: "Booking.com", vrbo: "VRBO", mmt: "MakeMyTrip",
  hostaway: "Hostaway", retalwise: "RentalWise",
};

function List({ title, sub, rows, money }: { title: string; sub: string; rows: { key: string; name: string; bookings: number; value: number | null }[]; money: boolean }) {
  const max = Math.max(1, ...rows.map(r => r.bookings));
  return (
    <section aria-label={title} className="min-w-0">
      <h3 className="font-[family-name:var(--font-display)] text-[15px] font-semibold text-[var(--haip-fg)]">{title}</h3>
      <p className="mb-2 text-xs text-[var(--haip-fg-subtle)]">{sub}</p>
      {rows.length === 0 ? <Empty>No bookings made in this period.</Empty> : (
        <>
          <div className="hidden grid-cols-[minmax(0,2fr)_repeat(2,minmax(0,1fr))] gap-x-3 border-b border-[var(--haip-border)] pb-1.5 text-[11.5px] font-semibold text-[var(--haip-fg-subtle)] md:grid">
            <span>Name</span><span className="text-right">Bookings</span><span className="text-right">Booked value</span>
          </div>
          <ul className="divide-y divide-[var(--haip-border)]">
            {rows.map(r => (
              <li key={r.key} className="grid grid-cols-2 gap-x-3 gap-y-1 py-2.5 md:grid-cols-[minmax(0,2fr)_repeat(2,minmax(0,1fr))] md:items-center">
                <span className="col-span-2 min-w-0 truncate text-[13px] font-medium text-[var(--haip-fg)] md:col-span-1">{r.name}<Bar value={r.bookings} max={max} /></span>
                <span className="text-[13px] tabular-nums md:text-right"><span className="block text-[11px] text-[var(--haip-fg-subtle)] md:hidden">Bookings</span>{num(r.bookings)}</span>
                <span className="text-[13px] tabular-nums md:text-right"><span className="block text-[11px] text-[var(--haip-fg-subtle)] md:hidden">Booked value</span>{money ? inr(r.value) : "—"}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

export function Breakdowns({ data }: { data: BusinessOverview }) {
  if (isRestricted(data.bookings)) return null;
  const b = data.bookings;
  return (
    <div className="haip-card grid grid-cols-1 gap-6 px-4 py-4 sm:px-6 sm:py-5 lg:grid-cols-2 lg:gap-8">
      <List title="Bookings by property" sub="Bookings made in this period" money={data.access.revenue}
        rows={b.by_property.map(r => ({ key: r.property_id, name: r.name, bookings: r.bookings, value: r.value }))} />
      <List title="Bookings by channel" sub="Where the guest booked, as recorded on the booking" money={data.access.revenue}
        rows={b.by_channel.map(r => ({ key: r.channel, name: CHANNEL_LABEL[r.channel.toLowerCase()] ?? r.channel, bookings: r.bookings, value: r.value }))} />
    </div>
  );
}
