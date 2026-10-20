"use client";
// Period, channel, property and agent. The selected period is always spelled out next to the controls, with its
// time zone, so a number can never be read without knowing what it covers.
// On phones the channel / property / agent pickers sit behind one "Filters" button (a bottom sheet) instead of taking two
// rows above the first number; a dot on the button says when any of them is narrowing the figures.
import { useState } from "react";
import { MobileFilterSheet, MobileFilterTrigger } from "@/components/ui/MobileFilterSheet";
import { cn } from "@/lib/utils";
import { periodLabel } from "./types";

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
  preset: string; customFrom: string; customTo: string; channel: string; propertyId: string; agentId: string; trend: "day" | "week" | "month";
}

const select = "h-11 w-full min-w-0 lg:h-9 sm:w-auto sm:max-w-[11rem] rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-2.5 text-[13px] text-[var(--haip-fg)] focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/25";

export function Controls({ value, onChange, properties, agents, from, to, tenantWide }: {
  value: Filters; onChange: (next: Filters) => void;
  properties: { id: string; name: string }[]; agents: { id: string; name: string }[];
  from?: string; to?: string; tenantWide: boolean;
}) {
  const set = (patch: Partial<Filters>) => onChange({ ...value, ...patch });
  const today = new Date().toISOString().slice(0, 10);
  const customReady = value.customFrom && value.customTo && value.customFrom <= value.customTo;
  const [sheetOpen, setSheetOpen] = useState(false);
  const active = [value.channel, value.propertyId, value.agentId].filter(Boolean).length;
  const pickers = (idPrefix: string, cls: string) => (<>
    <label className="sr-only" htmlFor={`${idPrefix}-channel`}>Channel</label>
    <select id={`${idPrefix}-channel`} className={cls} value={value.channel} onChange={e => set({ channel: e.target.value })}>
      {CHANNELS.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
    </select>
    {properties.length > 1 && (<>
      <label className="sr-only" htmlFor={`${idPrefix}-property`}>Property</label>
      <select id={`${idPrefix}-property`} className={cls} value={value.propertyId} onChange={e => set({ propertyId: e.target.value })}>
        <option value="">All properties</option>
        {properties.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
      </select>
    </>)}
    {tenantWide && agents.length > 0 && (<>
      <label className="sr-only" htmlFor={`${idPrefix}-agent`}>Agent</label>
      <select id={`${idPrefix}-agent`} className={cls} value={value.agentId} onChange={e => set({ agentId: e.target.value })}>
        <option value="">All agents</option>
        {agents.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
      </select>
    </>)}
  </>);
  return (
    <div className="space-y-3">
      <div className="hidden md:flex md:flex-wrap md:items-center md:gap-2">{pickers("oc", select)}</div>
      <div className="flex items-center gap-2 md:hidden">
        <MobileFilterTrigger onClick={() => setSheetOpen(true)} hasActiveFilters={active > 0} className="min-h-11 px-3.5" />
        {active > 0 && (
          <button type="button" onClick={() => set({ channel: "", propertyId: "", agentId: "" })}
            className="min-h-11 rounded-lg px-2 text-[12.5px] font-semibold text-primary">
            Clear {active === 1 ? "filter" : `${active} filters`}
          </button>
        )}
      </div>
      <MobileFilterSheet open={sheetOpen} onOpenChange={setSheetOpen} hasActiveFilters={active > 0}>
        {pickers("oc-m", cn(select, "h-12 text-[16px] sm:max-w-none"))}
        <button type="button" onClick={() => setSheetOpen(false)}
          className="mt-1 h-12 rounded-lg bg-primary text-[15px] font-semibold text-primary-foreground">Show figures</button>
      </MobileFilterSheet>

      {value.preset === "custom" && (
        <div className="grid grid-cols-2 items-end gap-2 text-[13px] sm:flex sm:flex-wrap">
          <label className="flex flex-col gap-1 text-[var(--haip-fg-subtle)]">From
            <input type="date" max={today} value={value.customFrom} onChange={e => set({ customFrom: e.target.value })} className={cn(select, "text-[16px] sm:text-[13px]")} />
          </label>
          <label className="flex flex-col gap-1 text-[var(--haip-fg-subtle)]">To
            <input type="date" max={today} min={value.customFrom || undefined} value={value.customTo} onChange={e => set({ customTo: e.target.value })} className={cn(select, "text-[16px] sm:text-[13px]")} />
          </label>
          {!customReady && <p className="col-span-2 text-[12px] text-[var(--haip-fg-subtle)] sm:pb-2">Pick both dates to apply.</p>}
        </div>
      )}

    </div>
  );
}
