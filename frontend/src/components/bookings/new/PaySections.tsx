"use client";
// 6 Payment (advance + balance schedule, the security deposit kept apart, what was paid right now) and 7 Confirmation
// (WhatsApp now with the exact text, or later).
import { Chip, Field, INPUT } from "@/components/quotes/ui";
import { cn } from "@/lib/utils";
import { cleanNumber, day, firstName, masked, money } from "./helpers";
import type { BookingForm, ComposeSetup, Preview } from "./types";
import { HINT, Note, Opt } from "./ui";

type SetFn = (patch: Partial<BookingForm>) => void;
const METHODS = [["upi", "UPI"], ["cash", "Cash"], ["bank_transfer", "Bank transfer"], ["razorpay", "Razorpay"]] as const;

export function PaymentSection({ form, set, setup, preview }: { form: BookingForm; set: SetFn; setup: ComposeSetup; preview: Preview | undefined }) {
  const s = preview?.schedule;
  const adv = Number(s?.advance ?? 0);
  const bal = Number(s?.balance ?? 0);
  const paid = Number(s?.paid ?? 0);
  const due = form.advanceDue || s?.advance_due || "";
  const last4 = form.guest?.phone_last4 ?? (form.newGuest ? form.newGuest.phone.replace(/\D/g, "").slice(-4) : null);
  return (
    <>
      <div className="grid gap-1">
        <span className="text-xs font-semibold text-[var(--haip-fg-2)]">Advance to confirm</span>
        <div className="flex flex-wrap gap-1.5">
          {(["25", "50", "100", "other"] as const).map(x => (
            <Chip key={x} on={form.advance === x} onClick={() => set({ advance: x })}>{x === "other" ? "Other" : x === "100" ? "Full" : `${x}%`}</Chip>
          ))}
        </div>
      </div>
      {form.advance === "other" && (
        <Field label="Advance amount (₹)" htmlFor="nb-adv">
          <input id="nb-adv" className={cn(INPUT, "num")} inputMode="numeric" value={form.advanceAmount} onChange={e => set({ advanceAmount: cleanNumber(e.target.value) })} />
        </Field>
      )}
      <div className="grid grid-cols-2 gap-2.5">
        <Field label="Advance due" htmlFor="nb-advdue">
          <input id="nb-advdue" type="date" className={INPUT} min={setup.today} max={form.checkIn || undefined} value={due}
            onChange={e => set({ advanceDue: e.target.value })} />
        </Field>
        <Field label="Balance due" htmlFor="nb-bal">
          <select id="nb-bal" className={INPUT} value={form.balanceRule} onChange={e => set({ balanceRule: e.target.value as BookingForm["balanceRule"] })}>
            <option value="pickup">Before pickup</option>
            <option value="7_days">7 days before</option>
          </select>
        </Field>
      </div>
      <div className="num grid overflow-hidden rounded-xl border border-[var(--haip-border)] text-[14px]">
        <div className="flex items-center justify-between gap-2.5 px-3 py-2">
          <span>Advance{form.advance !== "other" && form.advance !== "100" ? ` ${form.advance}%` : ""}
            <span className="block text-[12.5px] text-[var(--haip-fg-subtle)]">
              {form.payNow === "paid" ? (paid >= adv ? "paid today" : `${money(paid)} paid today, rest due ${day(due)}`) : `due ${day(due)}`}
            </span></span>
          <b>{money(adv)}</b>
        </div>
        {bal > 0 && (
          <div className="flex items-center justify-between gap-2.5 border-t border-[var(--haip-border)] px-3 py-2">
            <span>Balance<span className="block text-[12.5px] text-[var(--haip-fg-subtle)]">due {day(s?.balance_due)}{form.balanceRule === "pickup" ? ", before the caravan leaves" : ""}</span></span>
            <b>{money(bal)}</b>
          </div>
        )}
      </div>
      <div className="grid gap-2 rounded-xl border border-dashed border-[var(--haip-border-strong)] bg-[var(--haip-surface)] px-3 py-2.5 text-[14px]">
        <div className="grid grid-cols-2 items-end gap-2.5">
          <Field label="Security deposit (₹)" htmlFor="nb-dep">
            <input id="nb-dep" className={cn(INPUT, "num")} inputMode="numeric" value={form.deposit} onChange={e => set({ deposit: cleanNumber(e.target.value) })} />
          </Field>
          <Field label="Collect" htmlFor="nb-depw">
            <select id="nb-depw" className={INPUT} value={form.depositCollect} onChange={e => set({ depositCollect: e.target.value as BookingForm["depositCollect"] })}>
              <option value="pickup">At pickup</option>
              <option value="balance">With the balance</option>
            </select>
          </Field>
        </div>
        <span className={HINT}>Kept apart from the booking. Refunded after check-out. Never counted as revenue.</span>
      </div>
      <div className="grid gap-2" role="radiogroup" aria-label="Payment right now">
        <span className="text-xs font-semibold text-[var(--haip-fg-2)]">Payment right now</span>
        <Opt on={form.payNow === "none"} onClick={() => set({ payNow: "none" })} title="Nothing paid yet" sub={`HAIP reminds you on ${due ? day(due) : "the due date"}`} />
        <Opt on={form.payNow === "paid"} onClick={() => set({ payNow: "paid" })} title="Advance already paid" sub="UPI, cash, bank transfer or Razorpay" />
        <Opt on={form.payNow === "link"} onClick={() => set({ payNow: "link" })} title="Send a Razorpay link on WhatsApp now"
          sub={setup.payments.razorpay_connected ? `${money(adv)} to ${masked(last4)}` : "Razorpay is not connected yet"} />
      </div>
      {form.payNow === "paid" && (
        <div className="grid gap-2.5 rounded-xl border border-[var(--haip-border-strong)] bg-[var(--haip-surface)] p-3">
          <div className="flex flex-wrap gap-1.5">
            {METHODS.map(([k, l]) => <Chip key={k} on={form.payMethod === k} onClick={() => set({ payMethod: k })}>{l}</Chip>)}
          </div>
          <div className="grid grid-cols-2 gap-2.5">
            <Field label="Amount paid (₹)" htmlFor="nb-paid">
              <input id="nb-paid" className={cn(INPUT, "num")} inputMode="numeric" placeholder={String(adv || "")} value={form.payAmount}
                onChange={e => set({ payAmount: cleanNumber(e.target.value) })} />
            </Field>
            {form.payMethod === "cash" ? (
              <Field label="Received by" htmlFor="nb-recv"><input id="nb-recv" className={INPUT} value={setup.user.name} readOnly /></Field>
            ) : (
              <Field label={form.payMethod === "razorpay" ? "Payment id" : "UTR / reference"} htmlFor="nb-ref">
                <input id="nb-ref" className={INPUT} autoComplete="off" maxLength={120} placeholder={form.payMethod === "razorpay" ? "pay_Nx8…" : "e.g. 429817364512"}
                  value={form.payRef} onChange={e => set({ payRef: e.target.value })} />
              </Field>
            )}
          </div>
          <span className={HINT}>Recorded against the advance today. A receipt goes with the confirmation.</span>
        </div>
      )}
      {form.payNow === "link" && setup.payments.razorpay_connected && (
        <Note tone="info">HAIP sends a Razorpay link for {money(adv)}. The booking marks the advance paid by itself when the guest pays. The link stays open until {due ? day(due) : "the due date"}.</Note>
      )}
    </>
  );
}

export function ConfirmSection({ form, set, preview }: { form: BookingForm; set: SetFn; preview: Preview | undefined }) {
  const g = form.guest;
  return (
    <>
      <div className="flex flex-wrap gap-1.5">
        <Chip on={form.confirm === "now"} onClick={() => set({ confirm: "now" })}>Send on WhatsApp now</Chip>
        <Chip on={form.confirm === "later"} onClick={() => set({ confirm: "later" })}>Later, from the booking</Chip>
      </div>
      {form.confirm === "now" ? (
        <>
          <label className="flex min-h-11 items-center gap-2.5 text-[14.5px]">
            <input type="checkbox" className="size-5 accent-[var(--primary)]" checked={form.invoice} onChange={e => set({ invoice: e.target.checked })} />
            Attach the invoice (PDF)
          </label>
          {preview?.message_text
            ? <div data-testid="wa-preview" className="whitespace-pre-wrap rounded-[12px_12px_12px_4px] bg-[var(--haip-status-success-bg)] px-3 py-2.5 text-[14px] leading-relaxed text-[var(--haip-fg)] [overflow-wrap:anywhere]">{preview.message_text}</div>
            : <p className={HINT}>The message appears here once the guest, trip, caravan and price are filled in.</p>}
          <p className={HINT}>
            {g && preview?.window_open ? `${firstName(g.name)} ${g.wrote ?? "wrote recently"}, so it goes as a normal message.`
              : "Goes with the approved booking confirmation template (with the invoice) if the guest has not written in the last 24 hours."}
            {form.payNow === "link" && preview?.window_open ? " The payment link is in the same message." : ""}
          </p>
        </>
      ) : <p className={HINT}>Nothing goes to the guest now. You can send the confirmation later from the inbox.</p>}
    </>
  );
}
