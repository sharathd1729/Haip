"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Calendar, Filter, X } from "lucide-react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";

export interface LeadsFilters {
  source?: string;
  occasion?: string;
  assigned_to?: string;
  property_id?: string;
  enquiry_date_preset?: string;
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
  value, onChange, options, placeholder,
}: {
  value: string | undefined;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  placeholder: string;
}) {
  return (
    <select
      className="text-[11px] rounded-lg px-2 py-1 flex-shrink-0"
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

export function LeadsFilterBar({
  filters, onChange,
}: {
  filters: LeadsFilters;
  onChange: (f: LeadsFilters) => void;
}) {
  const [expanded, setExpanded] = useState(false);

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
    <div className="flex items-center gap-2 px-4 py-2 flex-wrap" style={{ borderBottom: "1px solid var(--haip-border)" }}>
      <button
        onClick={() => setExpanded(v => !v)}
        className="flex items-center gap-1.5 text-[11px] font-medium px-2.5 py-1 rounded-full border flex-shrink-0"
        style={{ borderColor: "var(--haip-border)", color: "var(--haip-fg-subtle)" }}
      >
        <Filter size={11} />
        Filters{activeCount > 0 ? ` (${activeCount})` : ""}
      </button>

      {expanded && (
        <>
          <div className="flex items-center gap-1">
            <Calendar size={11} style={{ color: "var(--haip-fg-subtle)" }} />
            <Select
              value={filters.enquiry_date_preset}
              onChange={v => set({ enquiry_date_preset: v || undefined })}
              options={ENQUIRY_PRESETS.filter(p => p.value)}
              placeholder="Enquiry date"
            />
          </div>

          <Select
            value={filters.checkin_date_preset}
            onChange={v => set({ checkin_date_preset: v || undefined, checkin_date_from: undefined, checkin_date_to: undefined })}
            options={CHECKIN_PRESETS.filter(p => p.value)}
            placeholder="Check-in date"
          />

          <Select
            value={filters.source}
            onChange={v => set({ source: v || undefined })}
            options={SOURCE_OPTIONS.map(s => ({ value: s, label: s.replace(/_/g, " ") }))}
            placeholder="Source"
          />

          <Select
            value={filters.assigned_to}
            onChange={v => set({ assigned_to: v || undefined })}
            options={users.map(u => ({ value: u.id, label: u.name }))}
            placeholder="Assigned to"
          />

          <Select
            value={filters.property_id}
            onChange={v => set({ property_id: v || undefined })}
            options={properties.map(p => ({ value: p.id, label: p.name }))}
            placeholder="Property"
          />

          <input
            className="text-[11px] rounded-lg px-2 py-1 flex-shrink-0 w-28"
            style={{ background: "var(--haip-card)", border: "1px solid var(--haip-border)", color: "var(--haip-fg)" }}
            placeholder="Occasion…"
            value={filters.occasion ?? ""}
            onChange={e => set({ occasion: e.target.value || undefined })}
          />

          {activeCount > 0 && (
            <button
              onClick={clearAll}
              className={cn("flex items-center gap-1 text-[11px] flex-shrink-0")}
              style={{ color: "var(--haip-fg-subtle)" }}
            >
              <X size={11} /> Clear
            </button>
          )}
        </>
      )}
    </div>
  );
}
