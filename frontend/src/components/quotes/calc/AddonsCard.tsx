"use client";
// Add-ons (priced like the base rate: one-time, per day, per guest, per guest per day; any price editable for this quote) and
// the discount + GST card.
import { X } from "@/lib/icons";
import { Card, CardBody, CardHeader } from "@/components/ui/kit";
import { cn } from "@/lib/utils";
import { BTN_GHOST, Field, INPUT } from "../ui";
import { GST_LABEL, UNIT_LABEL, addonAmount, cleanNumber, money, rowId } from "./calcHelpers";
import type { AddonRow, CalcForm, CalcSetup, Unit } from "./types";

const GRID = "grid grid-cols-2 gap-2 sm:grid-cols-[minmax(0,1fr)_104px_160px_92px] sm:items-center";

export function AddonsCard({ form, set }: { form: CalcForm; set: (patch: Partial<CalcForm>) => void }) {
  const update = (id: string, patch: Partial<AddonRow>) => set({ addons: form.addons.map(a => (a.id === id ? { ...a, ...patch } : a)) });
  return (
    <Card>
      <CardHeader title="Add-ons" description="Priced like the base rate: one-time, per day, per guest, or per guest per day. Edit any price for this quote." />
      <CardBody className="space-y-2">
        <div aria-hidden className="hidden text-[12px] font-semibold text-[var(--haip-fg-2)] sm:grid sm:grid-cols-[minmax(0,1fr)_104px_160px_92px] sm:gap-2">
          <span>Item</span><span>Price (₹)</span><span>Charged</span><span className="text-right">Amount</span>
        </div>
        {form.addons.length === 0 && <p className="text-[13px] text-[var(--haip-fg-subtle)]">No add-ons set up. Add your own line below.</p>}
        {form.addons.map(a => (
          <div key={a.id} className={cn(GRID, "border-b border-[var(--haip-border)] pb-2.5 last:border-b-0 sm:border-b-0 sm:pb-0")}>
            <div className="col-span-2 flex min-h-11 min-w-0 items-center gap-2.5 sm:col-span-1">
              <input type="checkbox" checked={a.on} onChange={e => update(a.id, { on: e.target.checked })}
                aria-label={`Include ${a.custom ? "this line" : a.name}`} className="size-5 shrink-0 accent-[var(--primary)]" />
              {a.custom ? (
                <>
                  <input className={INPUT} value={a.name} placeholder="e.g. Cake and decoration" aria-label="Line name" maxLength={80}
                    onChange={e => update(a.id, { name: e.target.value })} />
                  <button type="button" aria-label="Remove line" onClick={() => set({ addons: form.addons.filter(x => x.id !== a.id) })}
                    className="inline-flex size-11 shrink-0 items-center justify-center rounded-lg text-[var(--haip-fg-subtle)] hover:bg-[var(--haip-surface)] sm:size-9">
                    <X size={16} />
                  </button>
                </>
              ) : <span className="min-w-0 text-[14px]">{a.name}</span>}
            </div>
            <input className={cn(INPUT, "num")} inputMode="numeric" value={a.price} aria-label={`Price for ${a.name || "this line"}`}
              onChange={e => update(a.id, { price: cleanNumber(e.target.value) })} />
            <select className={INPUT} value={a.unit} aria-label="How it is charged" onChange={e => update(a.id, { unit: e.target.value as Unit })}>
              {(Object.keys(UNIT_LABEL) as Unit[]).map(u => <option key={u} value={u}>{UNIT_LABEL[u]}</option>)}
            </select>
            <span className={cn("num col-span-2 text-[14px] sm:col-span-1 sm:text-right", a.on ? "font-semibold" : "text-[var(--haip-fg-subtle)]")}>
              {a.on ? money(addonAmount(a, form.days, form.guests)) : "not added"}
            </span>
          </div>
        ))}
        <button type="button" className={BTN_GHOST}
          onClick={() => set({ addons: [...form.addons, { id: rowId(), name: "", price: "0", unit: "one_time", on: true, custom: true }] })}>
          + Add your own line
        </button>
      </CardBody>
    </Card>
  );
}

export function TaxCard({ form, set, setup }: { form: CalcForm; set: (patch: Partial<CalcForm>) => void; setup: CalcSetup }) {
  const rate = form.slab === "other" ? Number(cleanNumber(form.customRate) || 0) : Number(form.slab);
  const hint = !rate ? "No GST is charged on this quote."
    : form.inclusive ? `The rates above already include GST. The ${rate}% GST is shown inside the total.`
    : `GST at ${rate}% is added on top of the rates above.`;
  return (
    <Card>
      <CardHeader title="Discount and tax" />
      <CardBody className="space-y-3">
        <div className="grid grid-cols-1 gap-3 min-[420px]:grid-cols-3">
          <Field label="Discount" htmlFor="calc-disc">
            <select id="calc-disc" className={INPUT} value={form.discount} onChange={e => set({ discount: e.target.value })}>
              {setup.discount_options.map(d => <option key={d} value={d}>{d === "0" ? "None" : `${d}%`}</option>)}
            </select>
          </Field>
          <Field label="GST slab" htmlFor="calc-slab">
            <select id="calc-slab" className={INPUT} value={form.slab} onChange={e => set({ slab: e.target.value })}>
              {[...setup.gst_slabs, "other"].map(s => <option key={s} value={s}>{GST_LABEL[s] ?? `${s}%`}</option>)}
            </select>
          </Field>
          {form.slab === "other" && (
            <Field label="Rate (%)" htmlFor="calc-slabc">
              <input id="calc-slabc" className={cn(INPUT, "num")} inputMode="decimal" value={form.customRate}
                onChange={e => set({ customRate: cleanNumber(e.target.value) })} />
            </Field>
          )}
        </div>
        <label className="flex min-h-11 items-center gap-2.5 text-[14px] sm:min-h-10">
          <input type="checkbox" checked={form.inclusive} onChange={e => set({ inclusive: e.target.checked })} className="size-5 accent-[var(--primary)]" />
          Prices include GST
        </label>
        <p className="text-[12.5px] text-[var(--haip-fg-subtle)]">{hint}</p>
      </CardBody>
    </Card>
  );
}
