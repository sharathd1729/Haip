"use client";
// Period, channel, property and agent. The selected period is always spelled out next to the controls, with its
// time zone, so a number can never be read without knowing what it covers.
import { Tabs } from "@/components/ui/kit";
import { cn } from "@/lib/utils";
import { periodLabel } from "./types";

export const PRESETS = [
  { value: "today", label: "Today" },
  { value: "last_7d", label: "Last 7 days" },
  { value: "this_month", label: "This month" },
  { value: "last_month", label: "Last month" },
  { value: "custom", label: "Custom" },
] as const;

export const CHANNELS = [
  { value: "", label: "All channels" },
  { value: "whatsapp", label: "WhatsApp" },
  { value: "instagram", label: "Instagram" },
  { value: "facebook", label: "Facebook" },
  { value: "call", label: "Calls" },
  { value: "website", label: "Website & Google" },
  { value: "other", label: "Other sources" },
];

export interface Filters {
  preset: string; customFrom: string; customTo: string; channel: string; propertyId: string; agentId: string;
}

const select = "h-10 min-w-[8.5rem] max-w-[11rem] flex-1 sm:h-9 sm:flex-none rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-2.5 text-[13px] text-[var(--haip-fg)] focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/25";

export function Controls({ value, onChange, properties, agents, from, to, tenantWide }: {
  value: Filters; onChange: (next: Filters) => void;
  properties: { id: string; name: string }[]; agents: { id: string; name: string }[];
  from?: string; to?: string; tenantWide: boolean;
}) {
  const set = (patch: Partial<Filters>) => onChange({ ...value, ...patch });
  const today = new Date().toISOString().slice(0, 10);
  const customReady = value.customFrom && value.customTo && value.customFrom <= value.customTo;
  return (
    <div className="space-y-3">
      <Tabs label="Period" value={value.preset} onChange={v => set({ preset: v })} items={PRESETS.map(p => ({ value: p.value, label: p.label }))} className="max-w-full sm:w-fit" />
      <div className="flex flex-wrap items-center gap-2">
        <label className="sr-only" htmlFor="oc-channel">Channel</label>
        <select id="oc-channel" className={select} value={value.channel} onChange={e => set({ channel: e.target.value })}>
          {CHANNELS.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
        </select>
        {properties.length > 1 && (<>
          <label className="sr-only" htmlFor="oc-property">Property</label>
          <select id="oc-property" className={select} value={value.propertyId} onChange={e => set({ propertyId: e.target.value })}>
            <option value="">All properties</option>
            {properties.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </>)}
        {tenantWide && agents.length > 0 && (<>
          <label className="sr-only" htmlFor="oc-agent">Agent</label>
          <select id="oc-agent" className={select} value={value.agentId} onChange={e => set({ agentId: e.target.value })}>
            <option value="">All agents</option>
            {agents.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </>)}
      </div>

      {value.preset === "custom" && (
        <div className="flex flex-wrap items-end gap-2 text-[13px]">
          <label className="flex flex-col gap-1 text-[var(--haip-fg-subtle)]">From
            <input type="date" max={today} value={value.customFrom} onChange={e => set({ customFrom: e.target.value })} className={cn(select, "text-[16px] sm:text-[13px]")} />
          </label>
          <label className="flex flex-col gap-1 text-[var(--haip-fg-subtle)]">To
            <input type="date" max={today} min={value.customFrom || undefined} value={value.customTo} onChange={e => set({ customTo: e.target.value })} className={cn(select, "text-[16px] sm:text-[13px]")} />
          </label>
          {!customReady && <p className="pb-2 text-[12px] text-[var(--haip-fg-subtle)]">Pick both dates to apply.</p>}
        </div>
      )}

      {from && to && (
        <p className="text-[12.5px] text-[var(--haip-fg-subtle)]">
          <span className="font-semibold text-[var(--haip-fg-2)]">{periodLabel(from, to)}</span>
          {" · "}India time (IST), full days{" · compared with the equal period before it"}
        </p>
      )}
    </div>
  );
}
