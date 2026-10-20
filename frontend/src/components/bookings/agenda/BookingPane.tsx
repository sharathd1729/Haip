"use client";
// Where an opened booking shows: a side pane next to the agenda from 1100px (the list stays usable), a full-screen sheet on
// anything narrower (focus held inside, Escape or the back arrow closes it).
import { useEffect, useState } from "react";
import { Dialog } from "@base-ui/react/dialog";
import { BookingDetailView } from "@/components/bookings/BookingDetailView";

export const PANE_QUERY = "(min-width: 1100px)";

/** true from 1100px, false below, null until the first check in the browser (so a ?b= link never flashes the wrong one). */
export function useIsPaneWide(): boolean | null {
  const [wide, setWide] = useState<boolean | null>(null);
  useEffect(() => {
    const mq = window.matchMedia(PANE_QUERY);
    const apply = () => setWide(mq.matches);
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, []);
  return wide;
}

export function BookingSidePane({ id, onClose }: { id: string; onClose: () => void }) {
  return (
    <aside aria-label="Booking details" className="w-[520px] shrink-0 overflow-y-auto border-l border-[var(--haip-border)] bg-[var(--haip-bg,var(--background))]">
      <BookingDetailView key={id} id={id} variant="pane" onClose={onClose} />
    </aside>
  );
}

export function BookingFullSheet({ id, onClose }: { id: string | null; onClose: () => void }) {
  return (
    <Dialog.Root open={!!id} onOpenChange={o => { if (!o) onClose(); }}>
      <Dialog.Portal>
        <Dialog.Popup aria-label="Booking details"
          className="fixed inset-0 z-50 overflow-y-auto bg-[var(--haip-bg,var(--background))] pb-[max(1.5rem,env(safe-area-inset-bottom))] outline-none">
          <Dialog.Title className="sr-only">Booking details</Dialog.Title>
          {id && <BookingDetailView key={id} id={id} variant="pane" onClose={onClose} />}
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
