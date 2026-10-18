"use client";

import Link from "next/link";
import { NOTICE_TEXT } from "@/lib/publicLeads";

/** DPDP notice + the required checkbox. The text is the versioned notice the server records (lib/publicLeads.ts). */
export function ConsentCheckbox({
  checked,
  onChange,
  marketing,
  onMarketingChange,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  marketing?: boolean;
  onMarketingChange?: (v: boolean) => void;
}) {
  return (
    <div className="space-y-2">
      <label className="flex items-start gap-3 min-h-[44px] cursor-pointer">
        <input
          type="checkbox"
          checked={checked}
          onChange={e => onChange(e.target.checked)}
          className="mt-1 h-5 w-5 flex-shrink-0 accent-[var(--mkt-gold)]"
          required
        />
        <span className="text-xs leading-relaxed text-[var(--mkt-muted)]">
          {NOTICE_TEXT}{" "}
          <Link href="/privacy" className="underline text-[var(--mkt-gold)]">Privacy policy</Link>
          {" · "}
          <Link href="/grievance" className="underline text-[var(--mkt-gold)]">Grievance page</Link>
          <span className="text-[var(--haip-status-danger-fg)]"> *</span>
        </span>
      </label>
      {onMarketingChange && (
        <label className="flex items-start gap-3 min-h-[44px] cursor-pointer">
          <input
            type="checkbox"
            checked={!!marketing}
            onChange={e => onMarketingChange(e.target.checked)}
            className="mt-1 h-5 w-5 flex-shrink-0 accent-[var(--mkt-gold)]"
          />
          <span className="text-xs leading-relaxed text-[var(--mkt-muted)]">
            Also send me occasional product news from HAIP (optional).
          </span>
        </label>
      )}
    </div>
  );
}

/** Honeypot: invisible to people and screen readers; a bot that fills every field is stored as spam. */
export function Honeypot({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <div aria-hidden="true" className="absolute -left-[10000px] top-auto h-px w-px overflow-hidden">
      <label>
        Website
        <input type="text" name="website" tabIndex={-1} autoComplete="off" value={value} onChange={e => onChange(e.target.value)} />
      </label>
    </div>
  );
}
