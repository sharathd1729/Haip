"use client";
// A booking's details in a bottom sheet on the phone Bookings list: trip, vehicle, guests, then Total / Paid / Still due, and
// three actions: Collect (opens the existing Collect sheet: payment link or record a payment, nothing is charged by itself;
// only for roles that may record money), WhatsApp (the existing booking WhatsApp sheet) and Full page.
import Link from "next/link";
import { ExternalLink, IndianRupee, MessageCircle } from "@/lib/icons";
import { formatINR } from "@/lib/utils";
import { BottomSheet, RowTag, SheetActions, SheetLine, sheetActionCls } from "@/components/ui/kit";
import { guestName, isOverdue, nights, shortDay, type AgendaRow } from "@/lib/bookingAgenda";

/** "30–31 Oct" / "30 Oct – 2 Nov" / "30 Oct" for a stay (IST calendar dates). */
export function dateSpan(from: string, to: string): string {
  const a = shortDay(from).slice(4), b = shortDay(to).slice(4);
  if (from === to) return a;
  const [ad, am] = a.split(" "), [bd, bm] = b.split(" ");
  return am === bm ? `${ad}–${bd} ${bm}` : `${a} – ${b}`;
}

export function BookingRowSheet({ row, today, canCollect, onClose, onCollect, onWhatsApp }: {
  row: AgendaRow | null; today: string; canCollect: boolean; onClose: () => void;
  onCollect: (id: string) => void; onWhatsApp: (id: string) => void;
}) {
  if (!row) return null;
  const name = guestName(row);
  const guests = row.adults + row.children;
  const n = nights(row);
  const overdue = isOverdue(row, today);
  const owes = row.total_outstanding > 0 && row.raw_status !== "cancelled";
  return (
    <BottomSheet open onOpenChange={o => { if (!o) onClose(); }} title={`${row.trip ? `${name} · ${row.trip}` : name}, ${dateSpan(row.checkin, row.checkout)}`}
      description={row.external_id ? `Booking ${row.external_id}` : undefined}
      footer={<SheetActions>
        {canCollect && owes && (
          <button type="button" className={sheetActionCls(true)} onClick={() => onCollect(row.id)}><IndianRupee size={18} />Collect</button>
        )}
        {row.main_guest?.phone && (
          <button type="button" className={sheetActionCls(!(canCollect && owes))} onClick={() => onWhatsApp(row.id)}><MessageCircle size={18} />WhatsApp</button>
        )}
        <Link href={`/dashboard/bookings/${row.id}`} className={sheetActionCls()}><ExternalLink size={18} />Full page</Link>
      </SheetActions>}>
      <div className="grid gap-3">
        <div className="flex flex-wrap gap-1.5">
          {row.property?.name && <RowTag tone="brand">{row.property.name}</RowTag>}
          {guests > 0 && <RowTag>{row.adults} adult{row.adults === 1 ? "" : "s"}{row.children ? `, ${row.children} child${row.children === 1 ? "" : "ren"}` : ""}</RowTag>}
          <RowTag>{n > 0 ? `${n} night${n === 1 ? "" : "s"}` : "day trip"}</RowTag>
          {row.raw_status === "cancelled" && <RowTag tone="danger">Cancelled</RowTag>}
        </div>
        {row.total > 0 ? (
          <div>
            <SheetLine label="Total" value={formatINR(row.total)} strong />
            <SheetLine label="Paid" value={formatINR(row.total_paid)} />
            {owes && <SheetLine label={overdue ? "Overdue" : "Still due before trip"} value={formatINR(row.total_outstanding)} tone="due" />}
            {owes && row.next_payment_due_date && !overdue && (
              <p className="pt-1 text-[12.5px] text-[var(--haip-fg-subtle)]">Next instalment {formatINR(row.next_payment_amount)} due {shortDay(row.next_payment_due_date)}</p>
            )}
          </div>
        ) : <p className="text-[13px] text-[var(--haip-fg-subtle)]">No amount on this booking yet.</p>}
      </div>
    </BottomSheet>
  );
}
