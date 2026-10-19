"use client";
// One Filters button instead of six dropdowns: status, payment, vehicle, channel and check-in dates, applied together.
import { useEffect, useState } from "react";
import { ActionSheet, SheetChip, sheetBtn, sheetInput, sheetLabel } from "@/components/bookings/ActionSheet";
import { CHANNEL_OPTIONS, STATUS_OPTIONS } from "@/lib/bookings";
import { NO_FILTERS, PAY_OPTIONS, toggle, type Filters } from "@/lib/bookingAgenda";

export function FiltersSheet({ open, onClose, value, onApply, vehicles }: {
  open: boolean; onClose: () => void; value: Filters; onApply: (f: Filters) => void; vehicles: { id: string; name: string }[];
}) {
  const [draft, setDraft] = useState<Filters>(value);
  useEffect(() => { if (open) setDraft(value); }, [open, value]);

  const group = (key: "status" | "pay" | "vehicle" | "channel", label: string, options: { value: string; label: string }[]) => (
    <fieldset className="grid gap-1.5">
      <legend className="mb-1.5 text-[12.5px] font-semibold text-[var(--haip-fg-2)]">{label}</legend>
      <div className="flex flex-wrap gap-1.5">
        {options.map(o => (
          <SheetChip key={o.value} on={draft[key].includes(o.value)} onClick={() => setDraft(d => ({ ...d, [key]: toggle(d[key], o.value) }))}>{o.label}</SheetChip>
        ))}
      </div>
    </fieldset>
  );

  return (
    <ActionSheet open={open} onClose={onClose} title="Filters">
      {group("status", "Status", STATUS_OPTIONS)}
      {group("pay", "Payment", PAY_OPTIONS)}
      {vehicles.length > 0 && group("vehicle", "Vehicle", vehicles.map(v => ({ value: v.id, label: v.name })))}
      {group("channel", "Channel", CHANNEL_OPTIONS)}
      <fieldset className="grid gap-1.5">
        <legend className="mb-1.5 text-[12.5px] font-semibold text-[var(--haip-fg-2)]">Check-in between</legend>
        <div className="grid grid-cols-2 gap-2.5">
          <label className={sheetLabel}><span className="sr-only">From</span>
            <input type="date" aria-label="Check-in from" className={sheetInput} value={draft.from} max={draft.to || undefined} onChange={e => setDraft(d => ({ ...d, from: e.target.value }))} />
          </label>
          <label className={sheetLabel}><span className="sr-only">To</span>
            <input type="date" aria-label="Check-in to" className={sheetInput} value={draft.to} min={draft.from || undefined} onChange={e => setDraft(d => ({ ...d, to: e.target.value }))} />
          </label>
        </div>
      </fieldset>
      <div className="flex flex-wrap gap-2 pt-1">
        <button type="button" className={sheetBtn.primary} onClick={() => { onApply(draft); onClose(); }}>Show bookings</button>
        <button type="button" className={sheetBtn.secondary} onClick={() => setDraft(NO_FILTERS)}>Reset</button>
      </div>
    </ActionSheet>
  );
}
