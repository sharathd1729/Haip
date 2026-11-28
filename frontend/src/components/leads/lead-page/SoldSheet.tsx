"use client";
// Moving a lead to Sold (owner, 28 Nov 2026): a sold lead needs its booking, so the move asks for it. Used wherever a
// closed-won stage is picked: the lead page, the phone lead page, the phone list's row sheet and the desktop list's stage menu.
//   * the lead already has a booking -> the Won dialog (OutcomeSheet: why they booked), as before;
//   * no booking and the role can add one -> "Add the booking": the New booking form opens with this lead filled in, and
//     creating the booking moves the lead to Sold (booking_compose_create, the audited move);
//   * a role that cannot add bookings -> the Won dialog, so nobody is blocked from closing a lead.
// "The booking already exists" is for a booking that lives outside HAIP (a PMS) or is not linked to this lead yet.
import { useEffect, useState } from "react";
import Link from "next/link";
import { useSession } from "next-auth/react";
import { ArrowRight, Calendar } from "@/lib/icons";
import { Drawer } from "@/components/ui/kit";
import { OutcomeSheet } from "./OutcomeSheet";
import type { PipelineStage } from "./types";

const CAN_BOOK = ["owner", "manager", "reservations"];

export function SoldSheet({ open, onClose, inquiryId, name, stage, hasBooking }: {
  open: boolean; onClose: () => void; inquiryId: string; name: string; stage?: PipelineStage;
  /** true = a booking is linked to this lead. Left out (a list row), the sheet asks. */
  hasBooking?: boolean;
}) {
  const role = (useSession().data?.user as { role?: string } | undefined)?.role ?? "";
  const [skip, setSkip] = useState(false);          // "the booking already exists": go on to why they booked
  useEffect(() => { if (!open) setSkip(false); }, [open]);
  const label = stage?.label ?? "Sold";
  if (hasBooking || skip || !CAN_BOOK.includes(role)) {
    return <OutcomeSheet open={open} onClose={onClose} inquiryId={inquiryId} name={name} kind="won" stage={stage} />;
  }
  return (
    <Drawer open={open} onOpenChange={o => { if (!o) onClose(); }} title={`${label}: add the booking`}
      description={`${name} moves to ${label} when the booking is saved.`}>
      <div className="grid gap-3">
        <p className="text-[14px] text-[var(--haip-fg-2)]">
          The booking form opens with this lead filled in. Add the dates, what is booked, the price and any money already collected.
        </p>
        <Link href={`/dashboard/bookings/new?inquiry=${encodeURIComponent(inquiryId)}`} onClick={onClose}
          className="inline-flex min-h-12 cursor-pointer items-center justify-center gap-2 rounded-xl bg-primary px-4 text-[15px] font-semibold text-primary-foreground active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-2">
          <Calendar size={17} aria-hidden />Add the booking<ArrowRight size={15} aria-hidden />
        </Link>
        <button type="button" onClick={() => setSkip(true)}
          className="min-h-11 cursor-pointer rounded-xl px-4 text-[13.5px] font-semibold text-[var(--haip-fg-2)] hover:bg-[var(--haip-surface)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40">
          The booking already exists
        </button>
      </div>
    </Drawer>
  );
}
