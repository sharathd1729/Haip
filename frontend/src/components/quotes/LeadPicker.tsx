"use client";
// Pick the lead a quote is saved to: search by name or the last digits of the phone (same visibility as the Leads list).
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2, Search } from "@/lib/icons";
import api from "@/lib/api";
import type { LeadHit } from "@/app/dashboard/quotes/types";
import { BTN_GHOST, INPUT } from "./ui";

export function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export function LeadPicker({ value, onChange }: { value: LeadHit | null; onChange: (lead: LeadHit | null) => void }) {
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const q = useDebounced(text.trim(), 300);
  const hits = useQuery<LeadHit[]>({
    queryKey: ["quote-leads", q], queryFn: () => api.get("/quotes/leads", { params: { q } }).then(r => r.data),
    enabled: open && !value, staleTime: 30_000, retry: 0,
  });

  if (value) {
    return (
      <div className="flex min-h-11 flex-wrap items-center gap-2 rounded-lg border border-[var(--haip-border)] bg-[var(--haip-surface)] px-3 py-1.5 sm:min-h-9">
        <span className="min-w-0 flex-1 truncate text-[13px] font-semibold">{value.guest_name}
          {value.phone_last4 && <span className="num font-normal text-[var(--haip-fg-subtle)]"> · ••{value.phone_last4}</span>}
        </span>
        <button type="button" className={BTN_GHOST} onClick={() => { onChange(null); setOpen(true); }}>Change</button>
      </div>
    );
  }
  return (
    <div className="space-y-1.5">
      <div className="relative">
        <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--haip-fg-subtle)]" />
        <input id="quote-lead" type="search" value={text} placeholder="Search a lead by name or phone" autoComplete="off"
          onFocus={() => setOpen(true)} onChange={e => { setText(e.target.value); setOpen(true); }} className={`${INPUT} pl-9`} />
      </div>
      {open && (
        <div className="max-h-56 overflow-y-auto rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)]">
          {hits.isLoading ? (
            <p className="flex items-center gap-2 px-3 py-2.5 text-xs text-[var(--haip-fg-subtle)]"><Loader2 size={13} className="animate-spin" /> Searching…</p>
          ) : hits.isError ? (
            <p className="px-3 py-2.5 text-xs text-[var(--haip-status-danger-fg)]">Couldn&apos;t search leads. <button type="button" className="underline" onClick={() => hits.refetch()}>Try again</button></p>
          ) : !hits.data?.length ? (
            <p className="px-3 py-2.5 text-xs text-[var(--haip-fg-subtle)]">{q ? "No lead matches. Check the spelling, or add the lead from Leads first." : "No leads yet."}</p>
          ) : (
            <ul role="listbox" aria-label="Leads">
              {hits.data.map(h => (
                <li key={h.inquiry_id}>
                  <button type="button" role="option" aria-selected={false} onClick={() => { onChange(h); setOpen(false); setText(""); }}
                    className="flex min-h-11 w-full items-center gap-2 px-3 text-left text-[13px] hover:bg-[var(--haip-surface)] sm:min-h-9">
                    <span className="min-w-0 flex-1 truncate font-semibold">{h.guest_name}</span>
                    <span className="num shrink-0 text-xs text-[var(--haip-fg-subtle)]">{h.phone_last4 ? `••${h.phone_last4}` : ""}{h.source ? ` · ${h.source.replace(/_/g, " ").toLowerCase()}` : ""}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
