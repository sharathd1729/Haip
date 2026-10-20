"use client";
// The trip: Fixed package | Custom trip, dates, days, guests, and which caravan is free on those dates.
import Link from "next/link";
import { Card, CardBody, StatusPill } from "@/components/ui/kit";
import { cn } from "@/lib/utils";
import { Field, INPUT } from "../ui";
import { cleanNumber, money } from "./calcHelpers";
import type { CalcForm, CalcSetup, PriceResult } from "./types";

const SEG = "min-h-11 rounded-[9px] px-4 text-[13.5px] font-semibold transition-colors sm:min-h-10";

function NumberStep({ id, label, value, min, max, onChange }: { id: string; label: string; value: number; min: number; max: number; onChange: (v: number) => void }) {
  return (
    <Field label={label} htmlFor={id}>
      <input id={id} className={cn(INPUT, "num")} inputMode="numeric" value={String(value)}
        onChange={e => { const n = Number(e.target.value.replace(/\D/g, "")); onChange(Math.max(min, Math.min(max, n || min))); }} />
    </Field>
  );
}

export function TripCard({ form, set, setup, result }: {
  form: CalcForm; set: (patch: Partial<CalcForm>) => void; setup: CalcSetup; result: PriceResult | undefined;
}) {
  const pkg = setup.packages.find(p => p.key === form.packageKey);
  const c = setup.custom;
  const avail = result?.availability ?? [];
  const pending = setup.unpublished + setup.unpriced;
  return (
    <Card>
      <CardBody className="space-y-4">
        <div role="group" aria-label="Quote type" className="inline-flex gap-1 rounded-xl border border-[var(--haip-border-strong)] bg-[var(--haip-surface)] p-[3px]">
          {(["fixed", "custom"] as const).map(m => (
            <button key={m} type="button" aria-pressed={form.mode === m} onClick={() => set({ mode: m })}
              className={cn(SEG, form.mode === m ? "bg-[var(--haip-card)] text-primary shadow-[var(--haip-shadow-sm)]" : "text-[var(--haip-fg-subtle)]")}>
              {m === "fixed" ? "Fixed package" : "Custom trip"}
            </button>
          ))}
        </div>

        {form.mode === "fixed" ? (
          <div className="space-y-1.5">
            {setup.packages.length === 0 ? (
              <p className="text-[13px] text-[var(--haip-fg-subtle)]">No package is published yet. Use Custom trip, or publish packages in Settings.</p>
            ) : (
              <Field label="Package (by route)" htmlFor="calc-pkg">
                <select id="calc-pkg" className={INPUT} value={form.packageKey} onChange={e => set({ packageKey: e.target.value })}>
                  {setup.packages.map(p => (
                    <option key={p.key} value={p.key}>{p.name} — {p.basis === "per_day" ? `${money(p.price)} a day` : money(p.price)}</option>
                  ))}
                </select>
              </Field>
            )}
            <p className="text-[12.5px] text-[var(--haip-fg-subtle)]">
              Same price on both caravans. HAIP holds whichever one is vacant.
              {pkg?.free_guests ? ` ${pkg.free_guests} guests included.` : ""}
            </p>
            {pending > 0 && setup.permissions.can_manage && (
              <p className="text-[12.5px] text-[var(--haip-fg-subtle)]">
                {setup.unpublished > 0 && `${setup.unpublished} package${setup.unpublished === 1 ? "" : "s"} not published yet`}
                {setup.unpublished > 0 && setup.unpriced > 0 && ", "}
                {setup.unpriced > 0 && `${setup.unpriced} without a price`} —{" "}
                <Link href="/dashboard/settings/quotes" className="font-semibold text-primary underline">Publish</Link>
              </p>
            )}
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Field label="Trip name" htmlFor="calc-title" className="sm:col-span-3">
              <input id="calc-title" className={INPUT} value={form.customTitle} maxLength={120} onChange={e => set({ customTitle: e.target.value })} />
            </Field>
            <Field label="Rate per day (₹)" htmlFor="calc-rate">
              <input id="calc-rate" className={cn(INPUT, "num")} inputMode="numeric" value={form.ratePerDay} onChange={e => set({ ratePerDay: cleanNumber(e.target.value) })} />
            </Field>
            <Field label="Total km planned" htmlFor="calc-km">
              <input id="calc-km" className={cn(INPUT, "num")} inputMode="numeric" value={form.plannedKm} placeholder="optional" onChange={e => set({ plannedKm: cleanNumber(e.target.value) })} />
            </Field>
            <Field label="Extra km rate (₹)" htmlFor="calc-kmrate">
              <select id="calc-kmrate" className={INPUT} value={form.kmRate} onChange={e => set({ kmRate: e.target.value })}>
                {c.km_rates.map(r => <option key={r} value={String(Number(r))}>{Number(r)}</option>)}
              </select>
            </Field>
            <p className="text-[12.5px] text-[var(--haip-fg-subtle)] sm:col-span-3">
              {Number(c.included_km_per_day)} km a day and {c.free_guests} guests are included. Extra guests {money(c.extra_guest_per_day)} each {c.extra_guest_unit === "trip" ? "per trip" : "a day"}.
            </p>
          </div>
        )}

        <div className="grid grid-cols-1 gap-3 min-[420px]:grid-cols-3">
          <Field label="Start" htmlFor="calc-start">
            <input id="calc-start" type="date" className={INPUT} value={form.start} min={setup.today} onChange={e => set({ start: e.target.value })} />
          </Field>
          <NumberStep id="calc-days" label={pkg?.product === "same_day" && form.mode === "fixed" ? "Days (same day)" : "Days"} value={form.days} min={1} max={30} onChange={v => set({ days: v })} />
          <NumberStep id="calc-guests" label="Guests" value={form.guests} min={1} max={50} onChange={v => set({ guests: v })} />
        </div>

        <div className="flex flex-wrap items-center gap-1.5" aria-live="polite">
          {avail.map(v => (
            <StatusPill key={v.property_id} tone={v.status === "available" ? "success" : "danger"}>
              {v.property_name} · {v.status === "available" ? "Vacant" : v.status === "over_capacity" ? "Too small" : "Booked"}
            </StatusPill>
          ))}
          {avail.length > 0 && <span className="text-[12.5px] text-[var(--haip-fg-subtle)]">for these dates</span>}
          {avail.length > 0 && !avail.some(v => v.status === "available") && (
            <span className="text-[12.5px] font-semibold text-[var(--haip-status-danger-fg)]">No caravan is free: pick other dates before sending.</span>
          )}
        </div>
        {(result?.warnings ?? []).map(w => <p key={w} className="text-[12.5px] text-[var(--haip-status-warning-fg)]">{w}</p>)}
      </CardBody>
    </Card>
  );
}
