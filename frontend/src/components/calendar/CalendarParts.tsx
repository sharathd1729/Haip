"use client";
// Calendar pieces shared by the timeline (desktop), the month grid (phones) and the Bookings strip: the types and colours, and
// the sheet that opens when an entry is tapped. A booking opens its booking page and, when it came from a lead, that lead; a hold
// shows where it came from; a calendar event that named no unit ("Which villa?") can be put on one unit right here.
import { useState } from "react";
import Link from "next/link";
import { useSession } from "next-auth/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { differenceInCalendarDays, format, parseISO } from "date-fns";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { canViewBookings } from "@/lib/permissions";
import { cleanName, holdLabel, isWaiting, type HoldBlock } from "@/lib/calendarHolds";
import { useSegment } from "@/lib/segments";
import { Drawer, StatusPill } from "@/components/ui/kit";

export interface StayLite {
  id: string; check_in: string; check_out: string; status: string; guest_id?: string | null; guest_name: string; guest_phone?: string;
  adults: number; total_amount?: number | null; paid_amount?: number | null; channel_source: string; inquiry_id?: string | null;
  notes?: string;      // staff notes: the agent writes which caravan it is (Black / White)
  vehicle?: string;    // set when several units are drawn on one grid
}
export type BlockLite = HoldBlock;
export interface RowLite { property_id: string; property_name: string; stays: StayLite[]; blocks: BlockLite[] }

export type Entry =
  | { kind: "stay"; stay: StayLite; propertyName: string }
  | { kind: "block"; block: BlockLite; propertyName: string };

/** The legend's colours: sea green = direct booking, grey-green = held (a calendar event or a hand-made block), red = maintenance,
 *  amber = a calendar event waiting for its unit ("Which villa?"). */
export const BLOCK_TONE = (reason: string, waiting = false) => (waiting
  ? { bg: "bg-[var(--haip-status-warning-bg)]", text: "text-[var(--haip-status-warning-fg)]", border: "border-[var(--haip-status-warning-border)]", label: "Waiting for a unit" }
  : reason === "maintenance"
    ? { bg: "bg-[var(--haip-cal-maint)]", text: "text-white", border: "border-[var(--haip-cal-maint)]", label: "Maintenance" }
    : { bg: "bg-[var(--haip-cal-block)]", text: "text-[var(--haip-cal-block-fg)]", border: "border-[var(--haip-border-strong)]", label: reason === "owner_use" || reason === "personal" ? "Owner use (blocked)" : "Blocked" });

/** The faint amber stripe a unit row gets on the days a "Which villa?" event might be its own. */
export const WAITING_STRIPE = "bg-[repeating-linear-gradient(135deg,var(--haip-status-warning-border)_0_3px,var(--haip-status-warning-bg)_3px_6px)]";

/** Money still due on a DIRECT booking: both amounts known (they are null for roles without revenue.read) and less paid
 *  than the total. OTA bookings are collected by the OTA, so they never show as due here. Quotes and cancellations neither. */
export function moneyDue(s: Pick<StayLite, "status" | "total_amount" | "paid_amount" | "channel_source">): boolean {
  if (s.status === "cancelled" || s.status === "quoted") return false;
  if (s.channel_source && s.channel_source.toLowerCase() !== "direct") return false;
  return s.total_amount != null && s.paid_amount != null && s.total_amount - s.paid_amount > 0;
}

/** Money due: terracotta light with a terracotta left edge (--haip-cal-due-*); paid / direct stays sea green. */
export const DUE_TONE = { bg: "bg-[var(--haip-cal-due-bg)]", text: "text-[var(--haip-cal-due-fg)]", border: "border-[var(--haip-accent-line)]",
  edge: "shadow-[inset_3px_0_0_var(--haip-cal-due-edge)]" };

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

interface HoldOptions { block_id: string; needs_unit: boolean; units: { property_id: string; name: string; free: boolean }[] }

/** "Hold only this villa": the units of the event's calendar, free ones first; saving frees the others. */
function PickUnit({ block, onDone }: { block: BlockLite; onDone: () => void }) {
  const seg = useSegment();
  const qc = useQueryClient();
  const [picked, setPicked] = useState("");
  const opts = useQuery<HoldOptions>({ queryKey: ["hold-options", block.id], queryFn: () => api.get(`/ical-feeds/holds/${block.id}/options`).then(r => r.data) });
  const save = useMutation({
    mutationFn: () => api.post(`/ical-feeds/holds/${block.id}/assign`, { property_id: picked }).then(r => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["portfolio-calendar"] });
      qc.invalidateQueries({ queryKey: ["bookings-occupancy"] });
      onDone();
    },
  });
  const units = [...(opts.data?.units ?? [])].sort((a, b) => Number(b.free) - Number(a.free));
  const err = (save.error as { response?: { data?: { detail?: string }; status?: number } } | null)?.response;
  return (
    <div className="space-y-2 rounded-lg bg-[var(--haip-status-warning-bg)] p-3 text-sm text-[var(--haip-status-warning-fg)]">
      <p>The event names no {seg.unit.one}, so every {seg.unit.one} of this calendar is held on these dates. Pick the {seg.unit.one} to free the others.</p>
      {opts.isPending ? <p className="text-xs">Loading the {seg.unit.many}…</p> : opts.isError ? (
        <p role="alert" className="text-xs">{(opts.error as { response?: { status?: number } })?.response?.status === 403
          ? `Only an owner, manager or reservations can pick the ${seg.unit.one}.` : `Couldn't load the ${seg.unit.many}.`}</p>
      ) : (
        <>
          <label className="block">
            <span className="sr-only">Choose a {seg.unit.one}</span>
            <select value={picked} onChange={e => setPicked(e.target.value)}
              className="min-h-11 w-full rounded-lg border border-[var(--haip-status-warning-border)] bg-[var(--haip-card)] px-2 text-base text-[var(--haip-fg)] outline-none focus:ring-2 focus:ring-primary">
              <option value="">Choose a {seg.unit.one} free on these dates</option>
              {units.map(u => <option key={u.property_id} value={u.property_id} disabled={!u.free}>{u.name}{u.free ? "" : " (not free)"}</option>)}
            </select>
          </label>
          <button type="button" disabled={!picked || save.isPending} onClick={() => save.mutate()}
            className="flex min-h-11 w-full items-center justify-center rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground disabled:opacity-60">
            {save.isPending ? "Saving…" : `Hold only this ${seg.unit.one}`}
          </button>
          {err && <p role="alert" className="text-xs">{err.status === 403 ? `Only an owner, manager or reservations can pick the ${seg.unit.one}.` : err.data?.detail ?? "Couldn't save. Try again."}</p>}
        </>
      )}
    </div>
  );
}

export function EntrySheet({ entry, onClose, channelLabel }: { entry: Entry | null; onClose: () => void; channelLabel: (src: string) => string }) {
  const { data: session } = useSession();
  const seg = useSegment();
  const canOpenBooking = canViewBookings(session?.user?.role);   // the booking page needs bookings.read: don't offer a link that ends in "no access"
  const stay = entry?.kind === "stay" ? entry.stay : null;
  const block = entry?.kind === "block" ? entry.block : null;
  const waiting = !!block && isWaiting(block);
  const nights = stay
    ? differenceInCalendarDays(parseISO(stay.check_out), parseISO(stay.check_in))
    : block ? differenceInCalendarDays(parseISO(block.blocked_to), parseISO(block.blocked_from)) : 0;
  const link = "flex min-h-11 items-center justify-center rounded-lg px-4 text-sm font-semibold";
  const tone = block ? BLOCK_TONE(block.reason) : null;
  const where = waiting ? seg.whichUnit : entry?.propertyName;
  return (
    <Drawer
      open={!!entry} onOpenChange={o => { if (!o) onClose(); }}
      title={stay ? (cleanName(stay.guest_name) || "Guest") : block ? holdLabel(block) : ""}
      description={entry ? `${where} · ${stay ? day(stay.check_in) : day(block!.blocked_from)} → ${stay ? day(stay.check_out) : day(block!.blocked_to)} · ${nights} night${nights === 1 ? "" : "s"}` : undefined}
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
          {moneyDue(stay) && (
            <Row label="Still due">
              <span className={cn("rounded-md px-2 py-0.5 font-semibold", DUE_TONE.bg, DUE_TONE.text, DUE_TONE.edge)}>
                {money((stay.total_amount ?? 0) - (stay.paid_amount ?? 0))}
              </span>
            </Row>
          )}
          {!stay.inquiry_id && (
            <p className="rounded-lg bg-[var(--haip-surface)] p-3 text-xs text-[var(--haip-fg-subtle)]">This booking is not tied to a lead, so there is no lead to open.</p>
          )}
        </dl>
      )}
      {block && tone && (
        <dl className="space-y-3 text-sm">
          <Row label="Held as">
            <span className={cn("rounded-md border px-2 py-0.5 text-xs font-semibold", tone.bg, tone.text, tone.border)}>
              {block.event ? "From Google Calendar" : tone.label}
            </span>
          </Row>
          {block.event?.feed_name && <Row label="Calendar link">{block.event.feed_name}</Row>}
          {block.notes && !block.event && <Row label="Note">{block.notes}</Row>}
          {block.event && (
            <>
              {block.event.title && <Row label="Event title">{cleanName(block.event.title)}</Row>}
              {block.event.details.destination && <Row label="Destination">{block.event.details.destination}</Row>}
              {block.event.details.package && <Row label="Package">{block.event.details.package}</Row>}
              {block.event.details.guests && <Row label="Guests">{block.event.details.guests}</Row>}
            </>
          )}
          {waiting && <PickUnit block={block} onDone={onClose} />}
        </dl>
      )}
    </Drawer>
  );
}
