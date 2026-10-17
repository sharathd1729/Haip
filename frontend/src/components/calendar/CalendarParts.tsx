"use client";
// Calendar pieces shared by the timeline (desktop) and the month grid (phones): the types and colours, and the sheet that opens
// when an entry is tapped. A booking opens its booking page and, when it came from a lead, that lead; a block shows why dates are held.
import Link from "next/link";
import { useSession } from "next-auth/react";
import { differenceInCalendarDays, format, parseISO } from "date-fns";
import { cn } from "@/lib/utils";
import { canViewBookings } from "@/lib/permissions";
import { Drawer, StatusPill } from "@/components/ui/kit";

export interface StayLite {
  id: string; check_in: string; check_out: string; status: string; guest_id?: string | null; guest_name: string; guest_phone?: string;
  adults: number; total_amount?: number | null; channel_source: string; inquiry_id?: string | null;
  notes?: string;      // staff notes: the agent writes which caravan it is (Black / White)
  vehicle?: string;    // set when several vehicles are drawn on one grid
}
export interface BlockLite {
  id: string; blocked_from: string; blocked_to: string; reason: string; notes?: string; vehicle?: string;
  event?: { title: string; needs_vehicle: boolean; details: { guest_name?: string; phone?: string; destination?: string; package?: string; guests?: string } } | null;
}
export interface RowLite { property_id: string; property_name: string; stays: StayLite[]; blocks: BlockLite[] }

export type Entry =
  | { kind: "stay"; stay: StayLite; propertyName: string }
  | { kind: "block"; block: BlockLite; propertyName: string };

/** The three colours people were told to expect: green = direct booking, gray = blocked, red = maintenance. */
export const BLOCK_TONE = (reason: string) => (reason === "maintenance"
  ? { bg: "bg-[var(--haip-cal-maint)]", text: "text-white", border: "border-[var(--haip-cal-maint)]", label: "Maintenance" }
  : { bg: "bg-[var(--haip-cal-block)]", text: "text-[var(--haip-cal-block-fg)]", border: "border-[var(--haip-border-strong)]", label: reason === "owner_use" || reason === "personal" ? "Owner use (blocked)" : "Blocked" });

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
  const { data: session } = useSession();
  const canOpenBooking = canViewBookings(session?.user?.role);   // the booking page needs bookings.read: don't offer a link that ends in "no access"
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
          {canOpenBooking && <Link href={`/dashboard/bookings/${stay.id}`} className={cn(link, "bg-primary text-primary-foreground")}>Open booking</Link>}
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
          {stay.notes && <Row label="Notes">{stay.notes}</Row>}
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
