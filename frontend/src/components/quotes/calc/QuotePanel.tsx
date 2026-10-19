"use client";
// The right-hand panel: totals (from the server), "Change the price", the exact WhatsApp message, who it goes to, the
// Razorpay advance link, and Copy / Send / Save -- then the receipt of what got recorded.
import Link from "next/link";
import type { ReactNode } from "react";
import { Loader2 } from "@/lib/icons";
import { Card, CardBody, StatusPill } from "@/components/ui/kit";
import { cn } from "@/lib/utils";
import { BTN, BTN_GHOST, BTN_PRIMARY, Field, INPUT } from "../ui";
import { cleanNumber, money, receiptSteps, type ActionGate } from "./calcHelpers";
import type { CalcForm, LeadRow, PriceResult, Receipt } from "./types";

function Row({ label, value, className }: { label: ReactNode; value: ReactNode; className?: string }) {
  return <div className={cn("flex justify-between gap-3", className)}><span className="min-w-0">{label}</span><span className="shrink-0">{value}</span></div>;
}

export function Totals({ r }: { r: PriceResult }) {
  const pct = Number(r.gst_percent ?? 0);
  const gstName = pct ? `GST ${pct}%` : "No GST";
  const ov = r.override;
  return (
    <div className="num grid gap-1 text-[14px]">
      {(r.lines ?? []).map((l, i) => <Row key={`${l.label}-${i}`} label={l.label} value={money(l.amount)} />)}
      {r.discount && <Row label={`Discount ${Number(r.discount.percent)}%`} value={`- ${money(r.discount.amount)}`} />}
      {r.prices_include_gst ? (
        <>
          {ov && <Row label="Suggested total" value={<span className="text-[var(--haip-fg-subtle)] line-through">{money(r.net)}</span>} />}
          <Row className="border-t border-[var(--haip-border)] pt-1.5 font-[family-name:var(--font-display)] text-[22px] font-semibold" label={ov ? "Your price" : "Total"} value={money(r.total)} />
          <Row className="text-[13px] text-[var(--haip-fg-subtle)]" label={pct ? `Includes ${gstName}` : "No GST"} value={money(r.gst)} />
        </>
      ) : (
        <>
          {ov ? (
            <>
              <Row label="Suggested, before GST" value={<span className="text-[var(--haip-fg-subtle)] line-through">{money(r.net)}</span>} />
              <Row label="Your price, before GST" value={money(ov.price)} />
            </>
          ) : <Row label="Subtotal" value={money(r.net)} />}
          <Row label={gstName} value={money(r.gst)} />
          <Row className="border-t border-[var(--haip-border)] pt-1.5 font-[family-name:var(--font-display)] text-[22px] font-semibold" label="Total" value={money(r.total)} />
        </>
      )}
      <Row label={`Advance ${Number(r.advance_percent ?? 0)}% to confirm`} value={money(r.advance)} />
    </div>
  );
}

export function ReceiptBox({ receipt, lead, onOpenLead, copied }: { receipt: Receipt; lead: LeadRow | null; onOpenLead?: () => void; copied: boolean | null }) {
  const s = receiptSteps(receipt, lead);
  return (
    <div aria-live="polite" className="grid gap-2 rounded-xl bg-[var(--haip-primary-tint)] px-3.5 py-3">
      <h3 className="font-[family-name:var(--font-display)] text-[15px] font-semibold">{s.title}</h3>
      <ul className="grid gap-1.5 text-[13.5px]">
        {s.done.map(d => <li key={d} className="flex gap-2"><span aria-hidden className="w-3.5 shrink-0 font-bold text-primary">✓</span>{d}</li>)}
        {s.next.map(d => <li key={d} className="flex gap-2 text-[var(--haip-fg-2)]"><span aria-hidden className="w-3.5 shrink-0 text-[var(--haip-fg-subtle)]">○</span>{d}</li>)}
      </ul>
      {s.warning && <p className="text-[13px] font-semibold text-[var(--haip-status-warning-fg)]">{s.warning}</p>}
      {copied === false && (
        <div className="space-y-1">
          <p className="text-[12.5px] text-[var(--haip-fg-2)]">Your browser did not allow copying. Select the text and copy it:</p>
          <textarea readOnly value={receipt.message_text} className={cn(INPUT, "h-28 py-2")} onFocus={e => e.currentTarget.select()} />
        </div>
      )}
      <div className="flex flex-wrap gap-x-3">
        {onOpenLead
          ? <button type="button" className={BTN_GHOST} onClick={onOpenLead}>Open {(receipt.lead.guest_name || "the").split(" ")[0]}&apos;s lead</button>
          : <Link className={BTN_GHOST} href={`/dashboard/leads/${receipt.lead.inquiry_id}`}>Open {(receipt.lead.guest_name || "the").split(" ")[0]}&apos;s lead</Link>}
      </div>
    </div>
  );
}

export function QuotePanel({ form, set, result, pricing, failed, onRetry, gate, threshold, validDays, sendTo, acting, onAct, receipt, lead, copied, razorpay }: {
  form: CalcForm; set: (p: Partial<CalcForm>) => void; result: PriceResult | undefined; pricing: boolean; failed: boolean; onRetry: () => void;
  gate: ActionGate; threshold: string; validDays: number; sendTo: ReactNode; acting: "send" | "copy" | "save" | null;
  onAct: (a: "send" | "copy" | "save") => void; receipt: Receipt | null; lead: LeadRow | null; copied: boolean | null; razorpay: boolean;
}) {
  const ok = result?.ok;
  const ov = result?.override;
  const below = ov ? Number(ov.below_percent) : 0;
  return (
    <Card>
      <CardBody className="space-y-3.5">
        <div className="flex items-baseline justify-between gap-2">
          <h2 className="font-[family-name:var(--font-display)] text-[16px] font-semibold">Quote</h2>
          <span className="flex items-center gap-1.5 text-[12.5px] text-[var(--haip-fg-subtle)]">
            {pricing && <Loader2 size={12} className="animate-spin" aria-label="Updating the price" />}valid {validDays} day{validDays === 1 ? "" : "s"}
          </span>
        </div>

        {failed && !result ? (
          <div role="alert" className="text-[13px] text-[var(--haip-status-danger-fg)]">
            Couldn&apos;t price this trip. <button type="button" className="font-semibold underline" onClick={onRetry}>Try again</button>
          </div>
        ) : !result ? (
          <p className="text-[13px] text-[var(--haip-fg-subtle)]">{form.mode === "custom" ? "Enter the rate per day to see the price." : "Pick a package to see the price."}</p>
        ) : !ok ? (
          <p role="alert" className="text-[13px] font-semibold text-[var(--haip-status-danger-fg)]">{result.message}</p>
        ) : (
          <Totals r={result} />
        )}

        <div className="grid gap-2 border-t border-dashed border-[var(--haip-border-strong)] pt-2.5">
          <label className="flex min-h-11 items-center gap-2.5 text-[14px] sm:min-h-10">
            <input type="checkbox" checked={form.overrideOn} className="size-5 accent-[var(--primary)]"
              onChange={e => set({ overrideOn: e.target.checked, overridePrice: e.target.checked && !form.overridePrice && result?.net ? String(Math.round(Number(result.net))) : form.overridePrice })} />
            Change the price
          </label>
          {form.overrideOn && (
            <div className="grid grid-cols-1 gap-2.5 min-[420px]:grid-cols-2">
              <Field label={form.inclusive ? "Your price, incl. GST (₹)" : "Your price, before GST (₹)"} htmlFor="calc-ov">
                <input id="calc-ov" className={cn(INPUT, "num")} inputMode="numeric" value={form.overridePrice} onChange={e => set({ overridePrice: cleanNumber(e.target.value) })} />
              </Field>
              <Field label="Reason (team only)" htmlFor="calc-ovwhy">
                <input id="calc-ovwhy" className={INPUT} value={form.overrideReason} maxLength={300} placeholder="e.g. repeat guest" onChange={e => set({ overrideReason: e.target.value })} />
              </Field>
              <label className="flex min-h-11 items-center gap-2.5 text-[14px] min-[420px]:col-span-2 sm:min-h-10">
                <input type="checkbox" checked={form.showUsual} onChange={e => set({ showUsual: e.target.checked })} className="size-5 accent-[var(--primary)]" />
                Show the usual price to the guest
              </label>
            </div>
          )}
          {ov && ok && (
            <p className="text-[12.5px] text-[var(--haip-fg-subtle)]">
              {gate.needsOk || result?.approval?.needed
                ? <><StatusPill tone="warning">{below}% below suggested</StatusPill> More than {Number(threshold)}% off needs the owner&apos;s OK before it goes out{gate.needsOk ? "" : " (you can approve it yourself)"}.</>
                : below > 0 ? `${money(Number(result!.net) - Number(ov.price))} below the suggested price.` : `${money(Number(ov.price) - Number(result!.net))} above the suggested price.`}
            </p>
          )}
        </div>

        {ok && result?.message_text && (
          <div data-testid="quote-message" className="max-h-[380px] overflow-auto whitespace-pre-wrap rounded-[12px_12px_12px_4px] bg-[var(--haip-primary-tint)] px-3.5 py-3 text-[14px] leading-relaxed text-[var(--haip-fg)]">
            {result.message_text}
          </div>
        )}

        <div className="space-y-1"><span className="block text-xs font-semibold text-[var(--haip-fg-2)]">Send to</span>{sendTo}</div>

        <label className="flex min-h-11 items-center gap-2.5 text-[14px] sm:min-h-10">
          <input type="checkbox" checked={form.paymentLink} disabled={!razorpay} onChange={e => set({ paymentLink: e.target.checked })} className="size-5 accent-[var(--primary)]" />
          Add a Razorpay link for the advance
          {!razorpay && <Link href="/dashboard/settings/payments" className="text-[12.5px] font-semibold text-primary underline">Connect Razorpay</Link>}
        </label>

        <div className="grid grid-cols-2 gap-2">
          <button type="button" className={BTN} disabled={!gate.canCopy || !!acting} onClick={() => onAct("copy")}>
            {acting === "copy" ? <Loader2 size={14} className="animate-spin" /> : "Copy quote"}
          </button>
          <button type="button" className={BTN_PRIMARY} disabled={!gate.canSend || !!acting} onClick={() => onAct("send")}>
            {acting === "send" ? <Loader2 size={14} className="animate-spin" /> : gate.sendLabel}
          </button>
          <button type="button" className={cn(BTN_GHOST, "col-span-2 justify-center")} disabled={!gate.canSave || !!acting} onClick={() => onAct("save")}>
            {acting === "save" ? <Loader2 size={14} className="animate-spin" /> : "Save to the lead only"}
          </button>
        </div>
        {gate.hint && <p className="text-[12.5px] text-[var(--haip-fg-2)]">{gate.hint}</p>}
        <p className="text-[12.5px] text-[var(--haip-fg-subtle)]">Sent as a normal message if the guest wrote in the last 24 hours, otherwise with the approved quote template.</p>
        {receipt && <ReceiptBox receipt={receipt} lead={lead} copied={copied} />}
      </CardBody>
    </Card>
  );
}
