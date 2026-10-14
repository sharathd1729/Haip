"use client";
// Calendar pieces shared by the timeline (desktop) and the agenda (phones): the sheet that opens when an entry is tapped, and the
// agenda list itself. A booking opens its booking page and, when it came from a lead, that lead; a block shows why dates are held.
import Link from "next/link";
import { differenceInCalendarDays, format, parseISO } from "date-fns";
import { cn } from "@/lib/utils";
import { Drawer, EmptyState, StatusPill } from "@/components/ui/kit";

export interface StayLite {
  id: string; check_in: string; check_out: string; status: string; guest_id?: string | null; guest_name: string; guest_phone?: string;
  adults: number; total_amount?: number | null; channel_source: string; inquiry_id?: string | null;
}
export interface BlockLite {
  id: string; blocked_from: string; blocked_to: string; reason: string; notes?: string;
  event?: { title: string; needs_vehicle: boolean; details: { guest_name?: string; phone?: string; destination?: string; package?: string; guests?: string } } | null;
}
export interface RowLite { property_id: string; property_name: string; stays: StayLite[]; blocks: BlockLite[] }

export type Entry =
  | { kind: "stay"; stay: StayLite; propertyName: string }
  | { kind: "block"; block: BlockLite; propertyName: string };

/** The three colours people were told to expect: green = direct booking, gray = blocked, red = maintenance. */
export const BLOCK_TONE = (reason: string) => (reason === "maintenance"
  ? { bg: "bg-red-500", text: "text-white", border: "border-red-600", label: "Maintenance" }
  : { bg: "bg-gray-300", text: "text-gray-800", border: "border-gray-400", label: reason === "owner_use" || reason === "personal" ? "Owner use (blocked)" : "Blocked" });

const day = (iso: string) => format(parseISO(iso), "EEE d MMM");
const money = (n?: number | null) => (n != null ? `₹${Math.round(n).toLocaleString("en-IN")}` : null);

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4">
      <dt className="text-[var(--haip-fg-subtle)]">{label}</dt>
      <dd className="text-right font-medium">{children}</dd>
    </div>
  );
}

export function EntrySheet({ entry, onClose, channelLabel }: { entry: Entry | null; onClose: () => void; channelLabel: (src: string) => string }) {
  const stay = entry?.kind === "stay" ? entry.stay : null;
  const block = entry?.kind === "block" ? entry.block : null;
  const nights = stay
    ? differenceInCalendarDays(parseISO(stay.check_out), parseISO(stay.check_in))
    : block ? differenceInCalendarDays(parseISO(block.blocked_to), parseISO(block.blocked_from)) : 0;
  const link = "flex min-h-11 items-center justify-center rounded-lg px-4 text-sm font-semibold";
  const tone = block ? BLOCK_TONE(block.reason) : null;
  return (
    <Drawer
      open={!!entry} onOpenChange={o => { if (!o) onClose(); }}
      title={stay ? (stay.guest_name || "Guest") : block ? (block.event?.details.guest_name || tone!.label) : ""}
      description={entry ? `${entry.propertyName} · ${stay ? day(stay.check_in) : day(block!.blocked_from)} → ${stay ? day(stay.check_out) : day(block!.blocked_to)} · ${nights} night${nights === 1 ? "" : "s"}` : undefined}
      footer={stay && (
        <div className="flex w-full flex-col gap-2 sm:flex-row sm:justify-end">
          {stay.inquiry_id && (
            <Link href={`/dashboard/leads/${stay.inquiry_id}`} className={cn(link, "border border-[var(--haip-border)] hover:bg-[var(--haip-surface)]")}>Open lead</Link>
          )}
          <Link href={`/dashboard/bookings/${stay.id}`} className={cn(link, "bg-primary text-primary-foreground")}>Open booking</Link>
        </div>
      )}
    >
      {stay && (
        <dl className="space-y-3 text-sm">
          <Row label="Status">
            <StatusPill tone={stay.status === "cancelled" ? "danger" : stay.status === "confirmed" || stay.status === "checked_in" ? "success" : "neutral"}>
              {stay.status.replace("_", " ")}
            </StatusPill>
          </Row>
          <Row label="Booked through">{channelLabel(stay.channel_source)}</Row>
          <Row label="Guests">{stay.adults}</Row>
          {money(stay.total_amount) && <Row label="Total">{money(stay.total_amount)}</Row>}
          {!stay.inquiry_id && (
            <p className="rounded-lg bg-[var(--haip-surface)] p-3 text-xs text-[var(--haip-fg-subtle)]">This booking is not tied to a lead, so there is no lead to open.</p>
          )}
        </dl>
      )}
      {block && tone && (
        <dl className="space-y-3 text-sm">
          <Row label="Held as"><span className={cn("rounded-md border px-2 py-0.5 text-xs font-semibold", tone.bg, tone.text, tone.border)}>{tone.label}</span></Row>
          {block.notes && <Row label="Note">{block.notes}</Row>}
          {block.event && (
            <>
              <Row label="Calendar event">{block.event.title}</Row>
              {block.event.details.destination && <Row label="Destination">{block.event.details.destination}</Row>}
              {block.event.details.package && <Row label="Package">{block.event.details.package}</Row>}
              {block.event.details.guests && <Row label="Guests">{block.event.details.guests}</Row>}
              {block.event.needs_vehicle && (
                <p className="rounded-lg bg-[var(--haip-status-warning-bg)] p-3 text-xs text-[var(--haip-status-warning-fg)]">The event does not name a vehicle, so every vehicle is held until one is chosen.</p>
              )}
            </>
          )}
        </dl>
      )}
    </Drawer>
  );
}

/** Phones get a list, not a 30-column grid: each property's bookings and holds in date order, each row a full-width tap target. */
export function AgendaView({ rows, from, to, onOpen, chColor, channelLabel }: {
  rows: RowLite[]; from: string; to: string; onOpen: (e: Entry) => void;
  chColor: (src: string) => { bg: string; text: string }; channelLabel: (src: string) => string;
}) {
  if (rows.length === 0) return <EmptyState title="No properties to show" hint="Clear the filters or add a property." />;
  return (
    <div className="divide-y divide-[var(--haip-border)]">
      {rows.map(r => {
        const items = [
          ...r.stays
            .filter(s => s.status !== "cancelled" && s.check_out > from && s.check_in <= to)
            .map(s => ({ key: `s${s.id}`, at: s.check_in, entry: { kind: "stay", stay: s, propertyName: r.property_name } as Entry })),
          ...r.blocks
            .filter(b => b.blocked_to > from && b.blocked_from <= to)
            .map(b => ({ key: `b${b.id}`, at: b.blocked_from, entry: { kind: "block", block: b, propertyName: r.property_name } as Entry })),
        ].sort((a, b) => a.at.localeCompare(b.at));
        return (
          <section key={r.property_id} aria-label={r.property_name}>
            <h3 className="sticky top-0 z-10 bg-[var(--haip-surface)] px-4 py-2 text-xs font-bold uppercase tracking-wider text-[var(--haip-fg-subtle)] shadow-[0_1px_0_var(--haip-border)]">
              {r.property_name}
            </h3>
            {items.length === 0 ? (
              <p className="px-4 py-3 text-sm text-[var(--haip-fg-subtle)]">Free for the whole period.</p>
            ) : (
              <ul>
                {items.map(({ key, entry }) => {
                  const isStay = entry.kind === "stay";
                  const tone = isStay ? chColor(entry.stay.channel_source) : BLOCK_TONE(entry.block.reason);
                  const a = isStay ? entry.stay.check_in : entry.block.blocked_from;
                  const b = isStay ? entry.stay.check_out : entry.block.blocked_to;
                  const title = isStay ? (entry.stay.guest_name || "Guest") : (entry.block.event?.details.guest_name || BLOCK_TONE(entry.block.reason).label);
                  const sub = isStay ? channelLabel(entry.stay.channel_source) : BLOCK_TONE(entry.block.reason).label;
                  return (
                    <li key={key}>
                      <button type="button" onClick={() => onOpen(entry)} className="flex min-h-14 w-full items-center gap-3 px-4 py-2 text-left active:bg-[var(--haip-surface)]">
                        <span className={cn("h-10 w-1.5 shrink-0 rounded-full", tone.bg)} aria-hidden />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm font-semibold">{title}</span>
                          <span className="block text-xs text-[var(--haip-fg-subtle)]">{day(a)} → {day(b)} · {sub}</span>
                        </span>
                        <span className="text-[var(--haip-fg-subtle)]" aria-hidden>›</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
        );
      })}
    </div>
  );
}
