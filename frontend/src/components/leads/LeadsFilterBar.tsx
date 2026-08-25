"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Calendar, Filter, X } from "@/lib/icons";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { MobileFilterSheet, MobileFilterTrigger } from "@/components/ui/MobileFilterSheet";

export interface LeadsFilters {
  source?: string;
  occasion?: string;
  assigned_to?: string;
  property_id?: string;
  enquiry_date_preset?: string;
  // Backend already accepts these as raw ISO strings, spread verbatim as
  // query params by fetchStageLeads (leads.py's date_from/date_to params
  // -- named bare, unlike checkin_date_from/to's prefixed names below,
  // because that's the existing backend contract) -- only the "custom"
  // preset option and these two date inputs were missing on the frontend.
  date_from?: string;
  date_to?: string;
  checkin_date_preset?: string;
  checkin_date_from?: string;
  checkin_date_to?: string;
  booked_date_from?: string;
  booked_date_to?: string;
}

const ENQUIRY_PRESETS = [
  { value: "", label: "Any time" },
  { value: "last_7d", label: "Last 7 days" },
  { value: "last_14d", label: "Last 14 days" },
  { value: "custom", label: "Custom range…" },
];

const CHECKIN_PRESETS = [
  { value: "", label: "Any dates" },
  { value: "next_7d", label: "Next 7 days" },
  { value: "next_14d", label: "Next 14 days" },
  { value: "last_7d", label: "Last 7 days" },
  { value: "last_14d", label: "Last 14 days" },
];

const SOURCE_OPTIONS = [
  "wa_direct", "click_to_wa", "meta_ig", "inbound_call", "outbound_call",
  "ota_airbnb", "ota_booking", "ota_vrbo", "ota_mmt", "ota_goibibo",
  "channel_manager", "walk_in", "web_chat", "website", "referral", "email",
];

function Select({
  value, onChange, options, placeholder, className,
}: {
  value: string | undefined;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  placeholder: string;
  className?: string;
}) {
  return (
    <select
      className={cn("text-[11px] rounded-lg px-2 py-1 flex-shrink-0", className)}
      style={{ background: "var(--haip-card)", border: "1px solid var(--haip-border)", color: "var(--haip-fg)" }}
      value={value ?? ""}
      onChange={e => onChange(e.target.value)}
    >
      <option value="">{placeholder}</option>
      {options.map(o => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  );
}

function DateField({
  label, value, onChange, className,
}: {
  label: string;
  value: string | undefined;
  onChange: (v: string) => void;
  className?: string;
}) {
  return (
    <label className={cn("flex items-center gap-1.5 text-[11px] flex-shrink-0", className)} style={{ color: "var(--haip-fg-subtle)" }}>
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

// ─── Shared control set, rendered inline on desktop and stacked inside the
// mobile bottom sheet — same state, two layouts, so there's exactly one
// place these controls are defined. ────────────────────────────────────────

function FilterControls({
  filters, set, clearAll, activeCount, users, properties, layout,
}: {
  filters: LeadsFilters;
  set: (patch: Partial<LeadsFilters>) => void;
  clearAll: () => void;
  activeCount: number;
  users: { id: string; name: string }[];
  properties: { id: string; name: string }[];
  layout: "row" | "column";
}) {
  const wrapCls = layout === "row"
    ? "flex items-center gap-2 flex-wrap"
    : "flex flex-col gap-2.5";
  const fieldCls = layout === "column" ? "w-full" : undefined;

  return (
    <div className={wrapCls}>
      <div className={cn("flex items-center gap-1", fieldCls)}>
        <Calendar size={11} style={{ color: "var(--haip-fg-subtle)" }} />
        <Select
          value={filters.enquiry_date_preset}
          onChange={v => set({
            enquiry_date_preset: v || undefined,
            ...(v !== "custom" ? { date_from: undefined, date_to: undefined } : {}),
          })}
          options={ENQUIRY_PRESETS.filter(p => p.value)}
          placeholder="Enquiry date"
          className={fieldCls}
        />
      </div>

      {filters.enquiry_date_preset === "custom" && (
        <div className={cn("flex items-center gap-2", layout === "column" && "flex-col items-start gap-1.5")}>
          <DateField label="From" value={filters.date_from} onChange={v => set({ date_from: v || undefined })} className={fieldCls} />
          <DateField label="To" value={filters.date_to} onChange={v => set({ date_to: v || undefined })} className={fieldCls} />
        </div>
      )}

      <Select
        value={filters.checkin_date_preset}
        onChange={v => set({ checkin_date_preset: v || undefined, checkin_date_from: undefined, checkin_date_to: undefined })}
        options={CHECKIN_PRESETS.filter(p => p.value)}
        placeholder="Check-in date"
        className={fieldCls}
      />

      <Select
        value={filters.source}
        onChange={v => set({ source: v || undefined })}
        options={SOURCE_OPTIONS.map(s => ({ value: s, label: s.replace(/_/g, " ") }))}
        placeholder="Source"
        className={fieldCls}
      />

      <Select
        value={filters.assigned_to}
        onChange={v => set({ assigned_to: v || undefined })}
        options={users.map(u => ({ value: u.id, label: u.name }))}
        placeholder="Assigned to"
        className={fieldCls}
      />

      <Select
        value={filters.property_id}
        onChange={v => set({ property_id: v || undefined })}
        options={properties.map(p => ({ value: p.id, label: p.name }))}
        placeholder="Property"
        className={fieldCls}
      />

      <input
        className={cn("text-[11px] rounded-lg px-2 py-1 flex-shrink-0", layout === "row" ? "w-28" : "w-full")}
        style={{ background: "var(--haip-card)", border: "1px solid var(--haip-border)", color: "var(--haip-fg)" }}
        placeholder="Occasion…"
        value={filters.occasion ?? ""}
        onChange={e => set({ occasion: e.target.value || undefined })}
      />

      {activeCount > 0 && (
        <button
          onClick={clearAll}
          className="flex items-center gap-1 text-[11px] flex-shrink-0"
          style={{ color: "var(--haip-fg-subtle)" }}
        >
          <X size={11} /> Clear
        </button>
      )}
    </div>
  );
}

export function LeadsFilterBar({
  filters, onChange,
}: {
  filters: LeadsFilters;
  onChange: (f: LeadsFilters) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);

  const { data: users = [] } = useQuery<{ id: string; name: string }[]>({
    queryKey: ["users-lite"],
    queryFn: () => api.get("/users").then(r => r.data),
    staleTime: 5 * 60_000,
  });
  const { data: properties = [] } = useQuery<{ id: string; name: string }[]>({
    queryKey: ["properties-lite"],
    queryFn: () => api.get("/properties").then(r => r.data),
    staleTime: 5 * 60_000,
  });

  const activeCount = Object.values(filters).filter(Boolean).length;

  function set(patch: Partial<LeadsFilters>) {
    onChange({ ...filters, ...patch });
  }

  function clearAll() {
    onChange({});
  }

  return (
    <>
      {/* Desktop: inline expand/collapse, unchanged behavior */}
      <div className="hidden md:flex items-center gap-2 px-4 py-2 flex-wrap" style={{ borderBottom: "1px solid var(--haip-border)" }}>
        <button
          onClick={() => setExpanded(v => !v)}
          className="flex items-center gap-1.5 text-[11px] font-medium px-2.5 py-1 rounded-full border flex-shrink-0"
          style={{ borderColor: "var(--haip-border)", color: "var(--haip-fg-subtle)" }}
        >
          <Filter size={11} />
          Filters{activeCount > 0 ? ` (${activeCount})` : ""}
        </button>
        {expanded && (
          <FilterControls filters={filters} set={set} clearAll={clearAll} activeCount={activeCount} users={users} properties={properties} layout="row" />
        )}
      </div>

      {/* Mobile: compact trigger, controls live in a bottom sheet instead of
          wrapping across several lines inline. */}
      <div className="md:hidden px-4 py-2" style={{ borderBottom: "1px solid var(--haip-border)" }}>
        <MobileFilterTrigger onClick={() => setSheetOpen(true)} hasActiveFilters={activeCount > 0} />
      </div>
      <MobileFilterSheet open={sheetOpen} onOpenChange={setSheetOpen} hasActiveFilters={activeCount > 0}>
        <FilterControls filters={filters} set={set} clearAll={clearAll} activeCount={activeCount} users={users} properties={properties} layout="column" />
      </MobileFilterSheet>
    </>
  );
}
