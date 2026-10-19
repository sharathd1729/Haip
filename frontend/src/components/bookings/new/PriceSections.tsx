"use client";
// 4 Add-ons and 5 Price. Same units, discount steps, GST slabs and "Change the price" as the rate calculator; every amount shown
// comes from the server's preview (rate_calculator.py), never added up here.
import { UNIT_LABEL } from "@/components/quotes/calc/calcHelpers";
import type { Unit } from "@/components/quotes/calc/types";
import { BTN, Field, INPUT } from "@/components/quotes/ui";
import { cn } from "@/lib/utils";
import { X } from "@/lib/icons";
import { cleanNumber, money, rowId } from "./helpers";
import type { BookingForm, ComposeSetup, Preview } from "./types";
import { HINT, Note } from "./ui";

type SetFn = (patch: Partial<BookingForm>) => void;

export function AddonsSection({ form, set, preview }: { form: BookingForm; set: SetFn; preview: Preview | undefined }) {
  const lines = (preview?.price?.lines ?? []).filter(l => l.kind === "addon");
  const row = (i: number, patch: Partial<BookingForm["addons"][number]>) =>
    set({ addons: form.addons.map((a, j) => (j === i ? { ...a, ...patch } : a)) });
  return (
    <>
      <p className={HINT}>Same units as the rate calculator. Edit any price for this booking.</p>
      <div className="grid gap-2">
        {form.addons.map((a, i) => {
          const amount = lines.find(l => a.name && l.label.startsWith(a.name))?.amount;
          return (
            <div key={a.id} className="grid grid-cols-2 items-center gap-2 border-b border-[var(--haip-border)] pb-2.5 sm:grid-cols-[minmax(0,1fr)_100px_150px_84px] sm:border-0 sm:pb-0">
              <label className="col-span-2 flex min-h-11 min-w-0 items-center gap-2.5 text-[14.5px] sm:col-span-1">
                <input type="checkbox" className="size-5 shrink-0 accent-[var(--primary)]" checked={a.on} onChange={e => row(i, { on: e.target.checked })}
                  aria-label={`Add ${a.name || "this line"}`} />
                {a.custom ? (
                  <>
                    <input className={INPUT} value={a.name} placeholder="e.g. Photographer" aria-label="Line name" maxLength={80}
                      onChange={e => row(i, { name: e.target.value })} />
                    <button type="button" aria-label="Remove line" className="grid size-11 shrink-0 place-items-center rounded-lg text-[var(--haip-fg-subtle)]"
                      onClick={() => set({ addons: form.addons.filter((_, j) => j !== i) })}><X size={16} /></button>
                  </>
                ) : <span className="min-w-0">{a.name}</span>}
              </label>
              <input className={cn(INPUT, "num", !a.on && "max-sm:hidden")} inputMode="numeric" value={a.price} aria-label={`Price for ${a.name || "this line"}`}
                onChange={e => row(i, { price: cleanNumber(e.target.value) })} />
              <select className={cn(INPUT, !a.on && "max-sm:hidden")} value={a.unit} aria-label="How it is charged" onChange={e => row(i, { unit: e.target.value as Unit })}>
                {(Object.keys(UNIT_LABEL) as Unit[]).map(u => <option key={u} value={u}>{UNIT_LABEL[u]}</option>)}
              </select>
              <span className={cn("num col-span-2 text-[14px] sm:col-span-1 sm:text-right", a.on ? "font-bold" : "text-[var(--haip-fg-subtle)]")}>
                {a.on ? (amount ? money(amount) : "–") : "not added"}
              </span>
            </div>
          );
        })}
      </div>
      <button type="button" className={cn(BTN, "justify-self-start border-transparent text-primary")}
        onClick={() => set({ addons: [...form.addons, { id: rowId(), name: "", price: "0", unit: "one_time", on: true, custom: true }] })}>
        + Add your own line
      </button>
    </>
  );
}

export function Totals({ preview, form }: { preview: Preview | undefined; form: BookingForm }) {
  const p = preview?.price;
  return (
    <div className="num grid gap-1 text-[14px]" data-testid="totals">
      {p ? p.lines.map(l => (
        <div key={l.label} className="flex justify-between gap-3"><span className="min-w-0 [overflow-wrap:anywhere]">{l.label}</span><span className="whitespace-nowrap">{money(l.amount)}</span></div>
      )) : <div className="flex justify-between text-[13px] text-[var(--haip-fg-subtle)]"><span>Pick a package to see the price</span><span>–</span></div>}
      {p?.discount && <div className="flex justify-between"><span>Discount {p.discount.percent}%</span><span>−{money(p.discount.amount)}</span></div>}
      {p?.override && <div className="flex justify-between text-[13px] text-[var(--haip-fg-subtle)]"><span>Usual price</span><span className="line-through">{money(p.suggested_total)}</span></div>}
      {p && <div className="flex justify-between text-[13px] text-[var(--haip-fg-subtle)]"><span>GST {Number(p.gst_percent)}% {p.prices_include_gst || form.overrideOn ? "(included)" : "(added)"}</span><span>{money(p.gst)}</span></div>}
      <div className="flex justify-between border-t border-[var(--haip-border)] pt-1.5 font-[family-name:var(--font-display)] text-[22px] font-semibold">
        <span>Booking total</span><span>{money(p?.total ?? 0)}</span>
      </div>
      <div className="text-[13px] text-[var(--haip-fg-subtle)]">Security deposit is kept apart, not in this total</div>
    </div>
  );
}

export function PriceSection({ form, set, setup, preview }: { form: BookingForm; set: SetFn; setup: ComposeSetup; preview: Preview | undefined }) {
  const qm = preview?.quote_match;
  return (
    <>
      <Totals preview={preview} form={form} />
      {qm && (qm.same
        ? <Note tone="ok">Same as quote {qm.number}: {money(qm.quoted)}. The guest sees no surprise.</Note>
        : <Note tone="warn" actions={<button type="button" className={BTN}
            onClick={() => set({ overrideOn: true, overridePrice: String(Number(qm.quoted)), overrideReason: `Price agreed in ${qm.number}` })}>Keep {money(qm.quoted)}</button>}>
            Quote {qm.number} said {money(qm.quoted)}. With your changes it is {money(preview?.price?.total)}.
          </Note>)}
      <div className="grid grid-cols-2 gap-2.5">
        <Field label="Discount" htmlFor="nb-disc">
          <select id="nb-disc" className={INPUT} value={form.discount} onChange={e => set({ discount: e.target.value })}>
            {setup.discount_options.map(d => <option key={d} value={d}>{d === "0" ? "None" : `${d}%`}</option>)}
          </select>
        </Field>
        <Field label="GST slab" htmlFor="nb-slab">
          <select id="nb-slab" className={INPUT} value={form.slab} onChange={e => set({ slab: e.target.value })}>
            {setup.gst_slabs.map(s => <option key={s} value={s}>{s === "0" ? "0% · no GST" : `${s}%`}</option>)}
          </select>
        </Field>
      </div>
      <label className="flex min-h-11 items-center gap-2.5 text-[14.5px]">
        <input type="checkbox" className="size-5 accent-[var(--primary)]" checked={form.inclusive} onChange={e => set({ inclusive: e.target.checked })} />
        Prices include GST
      </label>
      <label className="flex min-h-11 items-center gap-2.5 text-[14.5px]">
        <input type="checkbox" className="size-5 accent-[var(--primary)]" checked={form.overrideOn} onChange={e => set({ overrideOn: e.target.checked })} />
        Change the price
      </label>
      {form.overrideOn && (
        <div className="grid grid-cols-2 gap-2.5">
          <Field label={form.inclusive ? "Final price incl. GST (₹)" : "Price before GST (₹)"} htmlFor="nb-ov">
            <input id="nb-ov" className={cn(INPUT, "num")} inputMode="numeric" value={form.overridePrice} onChange={e => set({ overridePrice: cleanNumber(e.target.value) })} />
          </Field>
          <Field label="Reason (team only)" htmlFor="nb-ovr">
            <input id="nb-ovr" className={INPUT} maxLength={300} placeholder="e.g. repeat guest" value={form.overrideReason} onChange={e => set({ overrideReason: e.target.value })} />
          </Field>
        </div>
      )}
    </>
  );
}
