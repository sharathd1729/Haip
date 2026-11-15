"use client";
// Up to 3 WhatsApp reply buttons on the next message from the inbox (sent as `interactive`, services/wa_interactive.py).
import { useState } from "react";
import { Plus, X } from "@/lib/icons";

export function ReplyButtonsBar({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  const [open, setOpen] = useState(value.length > 0);
  if (!open) {
    return (
      <div className="border-t border-[var(--haip-border)] px-4 py-1.5">
        <button type="button" onClick={() => { setOpen(true); onChange(["", ""]); }}
          className="inline-flex min-h-9 items-center gap-1.5 text-[13px] font-medium text-primary"><Plus size={14} /> Add reply buttons</button>
      </div>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-2 border-t border-[var(--haip-border)] px-4 py-2">
      <span className="text-[12.5px] text-[var(--haip-fg-subtle)]">Buttons the guest can tap:</span>
      {[0, 1, 2].map(i => (
        <input key={i} maxLength={20} value={value[i] ?? ""} placeholder={["Yes", "No", "Call me"][i]} aria-label={`Reply button ${i + 1}`}
          onChange={e => { const v = [...value, "", "", ""].slice(0, 3); v[i] = e.target.value; onChange(v); }}
          className="min-h-9 w-28 rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-2 text-[16px] sm:text-[13px]" />
      ))}
      <button type="button" aria-label="Remove reply buttons" onClick={() => { setOpen(false); onChange([]); }}
        className="flex size-9 items-center justify-center rounded-full"><X size={14} /></button>
    </div>
  );
}
