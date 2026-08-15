"use client";

import { cn } from "@/lib/utils";

export interface DateRangeValue {
  preset: string;
  date_from?: string;
  date_to?: string;
}

// Matches backend/app/services/date_presets.py's VALID_PRESETS exactly --
// keep these two lists in sync if either changes.
export const DATE_PRESETS = [
  { value: "today", label: "Today" },
  { value: "yesterday", label: "Yesterday" },
  { value: "last_7d", label: "Last 7 days" },
  { value: "last_14d", label: "Last 14 days" },
  { value: "this_month", label: "This month" },
  { value: "last_month", label: "Last month" },
  { value: "custom", label: "Custom range…" },
];

function Select({
  value, onChange, options, className,
}: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  className?: string;
}) {
  return (
    <select
      className={cn("text-[11px] rounded-lg px-2 py-1.5 flex-shrink-0 font-medium", className)}
      style={{ background: "var(--haip-card)", border: "1px solid var(--haip-border)", color: "var(--haip-fg)" }}
      value={value}
      onChange={e => onChange(e.target.value)}
    >
      {options.map(o => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  );
}

function DateField({
  label, value, onChange,
}: {
  label: string;
  value: string | undefined;
  onChange: (v: string) => void;
}) {
  return (
    <label className="flex items-center gap-1.5 text-[11px] flex-shrink-0" style={{ color: "var(--haip-fg-subtle)" }}>
      {label}
      <input
        type="date"
        value={value ?? ""}
        onChange={e => onChange(e.target.value)}
        className="text-[11px] rounded-lg px-1.5 py-1"
        style={{ background: "var(--haip-card)", border: "1px solid var(--haip-border)", color: "var(--haip-fg)" }}
      />
    </label>
  );
}

/**
 * Persistent top-nav date-range filter (role-aware dashboard rebuild,
 * `claude-fable-5-lovely-biscuit.md`). Generalized deliberately -- Leads360
 * and Calls each have their own partial preset sets today
 * (LeadsFilterBar.tsx: last_7d/14d/custom only; Calls page: raw date
 * inputs, no presets at all) -- this is the shared shape both could adopt
 * later without a rewrite, not required for this ticket.
 *
 * `children` is a slot for page-specific extra filters (channel/agent/
 * property) rendered inline after the date control, so this component
 * stays focused on the date piece.
 */
export function DateRangeFilterBar({
  value, onChange, children,
}: {
  value: DateRangeValue;
  onChange: (v: DateRangeValue) => void;
  children?: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <Select
        value={value.preset}
        onChange={preset => onChange({ preset, date_from: value.date_from, date_to: value.date_to })}
        options={DATE_PRESETS}
      />
      {value.preset === "custom" && (
        <>
          <DateField label="From" value={value.date_from} onChange={d => onChange({ ...value, date_from: d })} />
          <DateField label="To" value={value.date_to} onChange={d => onChange({ ...value, date_to: d })} />
        </>
      )}
      {children}
    </div>
  );
}
