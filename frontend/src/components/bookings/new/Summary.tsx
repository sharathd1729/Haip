"use client";
// The summary of the booking being made: the desktop side card (sticky, with the clickable "Still needed" list and Create), the
// phone bottom bar (total + the first missing item + Review) and the phone review sheet (summary, WhatsApp text, Create).
// After Create: the receipt of what HAIP did.
import Link from "next/link";
import { useEffect, useRef, type ReactNode } from "react";
import { Check, X } from "@/lib/icons";
import { BTN, BTN_PRIMARY } from "@/components/quotes/ui";
import { Card, CardBody } from "@/components/ui/kit";
import { cn } from "@/lib/utils";
import { clock, day, firstName, masked, money, nightsBetween, span } from "./helpers";
import type { BookingForm, ComposeReceipt, ComposeSetup, Preview, Problem, Section } from "./types";
import { HINT, Note } from "./ui";

interface SumProps { form: BookingForm; setup: ComposeSetup; preview: Preview | undefined }

function Row({ k, v, sub }: { k: string; v: ReactNode; sub?: ReactNode }) {
  return (
    <div className="grid grid-cols-[88px_minmax(0,1fr)] gap-2.5 border-t border-[var(--haip-border)] py-2 text-[14px] first:border-t-0 first:pt-0">
      <span className="pt-px text-[12.5px] font-semibold text-[var(--haip-fg-subtle)]">{k}</span>
      <span className="grid min-w-0 gap-px [overflow-wrap:anywhere]">
        <span>{v}</span>{sub && <span className="text-[12.5px] text-[var(--haip-fg-subtle)]">{sub}</span>}
      </span>
    </div>
  );
}

export function SummaryRows({ form, setup, preview }: SumProps) {
  const g = form.guest;
  const name = g?.name || form.newGuest?.name || (form.newGuest ? "New guest" : "");
  const pkg = form.mode === "custom" ? form.customTitle : setup.packages.find(p => p.key === form.packageKey)?.name;
  const n = nightsBetween(form.checkIn, form.checkOut);
  const on = form.addons.filter(a => a.on && a.name);
  const p = preview?.price;
  const s = preview?.schedule;
  const src = setup.sources.find(x => x.value === form.newGuest?.source)?.label;
  return (
    <div className="grid" data-testid="summary">
      <Row k="Guest" v={name || <span className="font-semibold text-[var(--haip-status-danger-fg)]">Not picked</span>}
        sub={g ? `${masked(g.phone_last4)} · ${g.tag}` : form.newGuest ? `new, came from ${src ?? ""}` : undefined} />
      <Row k="Trip" v={pkg || <span className="font-semibold text-[var(--haip-status-danger-fg)]">No package</span>}
        sub={form.checkIn && form.checkOut ? `${day(form.checkIn)} ${clock(form.checkInTime)} → ${day(form.checkOut)} ${clock(form.checkOutTime)} · ${n ? `${n} night${n > 1 ? "s" : ""}` : "day trip"} · ${form.guests} guests${form.pickup ? ` · ${form.pickup}` : ""}` : "Dates not picked"} />
      <Row k="Caravan" v={preview?.vehicle ? `${preview.vehicle.name}${form.vehicle === "auto" ? " (first free)" : ""}` : preview?.vehicles ? "None free" : "After dates"}
        sub={form.interior ? `Interior: ${form.interior}` : "Interior not picked"} />
      <Row k="Add-ons" v={on.length ? on.map(a => a.name.replace(/ \(.+\)/, "")).join(", ") : "None"} />
      <Row k="Price" v={<b className="num">{money(p?.total ?? 0)}</b>}
        sub={p ? `${Number(p.gst) ? `${money(p.gst)} GST ${p.prices_include_gst ? "included" : "added"}` : "No GST"}${p.discount ? ` · ${p.discount.percent}% off` : ""}${p.override ? ` · changed: ${form.overrideReason || "no reason yet"}` : ""}` : undefined} />
      <Row k="Payment" v={<span className="num">Advance {money(s?.advance)} · balance {money(s?.balance)}</span>}
        sub={`${form.payNow === "paid" ? `${money(s?.paid)} paid by ${form.payMethod.replace("_", " ")}` : form.payNow === "link" ? "Razorpay link goes now" : "Nothing paid yet"} · deposit ${money(form.deposit || 0)} kept apart`} />
      <Row k="WhatsApp" v={form.confirm === "now" ? `Confirmation${form.invoice ? " + invoice" : ""} now` : "Not now"} />
    </div>
  );
}

function StillNeeded({ problems, showErr, onJump, underline }: { problems: Problem[]; showErr: boolean; onJump: (s: Section) => void; underline?: boolean }) {
  return (
    <Note tone={showErr ? "bad" : "info"}>
      <b>{underline ? "Fix before creating" : "Still needed"}</b>
      <ul className="mt-1 grid list-disc gap-0.5 pl-4" data-testid="still-needed">
        {problems.map(p => (
          <li key={p.section + p.message}>
            <button type="button" onClick={() => onJump(p.section)} className={cn("min-h-8 text-left", underline && "underline")}>{p.message}</button>
          </li>
        ))}
      </ul>
    </Note>
  );
}

export function SummaryAside({ problems, showErr, onJump, onCreate, creating, ...rest }: SumProps & {
  problems: Problem[]; showErr: boolean; onJump: (s: Section) => void; onCreate: () => void; creating: boolean;
}) {
  const s = rest.preview?.schedule;
  const due = rest.form.advanceDue || s?.advance_due;
  return (
    <>
      <Card><CardBody className="space-y-2 pt-4"><h2 className="font-[family-name:var(--font-display)] text-[17px] font-semibold">Summary</h2><SummaryRows {...rest} /></CardBody></Card>
      <Card>
        <CardBody className="space-y-3 pt-4">
          <div className="num grid gap-1 text-[14px]">
            <div className="flex justify-between font-[family-name:var(--font-display)] text-[22px] font-semibold"><span>Booking total</span><span>{money(s?.total)}</span></div>
            <div className="flex justify-between text-[13px] text-[var(--haip-fg-subtle)]"><span>Advance {rest.form.payNow === "paid" ? "paid" : `due ${day(due)}`}</span><span>{money(s?.advance)}</span></div>
            <div className="flex justify-between text-[13px] text-[var(--haip-fg-subtle)]"><span>Deposit, kept apart</span><span>{money(rest.form.deposit || 0)}</span></div>
          </div>
          {problems.length ? <StillNeeded problems={problems} showErr={showErr} onJump={onJump} />
            : <Note tone="ok">Ready. {rest.preview?.vehicle?.name ?? "The caravan"} is free and held while you create.</Note>}
          <button type="button" className={cn(BTN_PRIMARY, "min-h-[50px] w-full text-[15.5px]")} onClick={onCreate} disabled={creating}>
            {creating ? "Creating…" : "Create booking"}
          </button>
          <p className={HINT}>{rest.form.confirm === "now" ? `Sends the confirmation to ${firstName(rest.form.guest?.name || rest.form.newGuest?.name)} on WhatsApp.` : "Nothing goes to the guest."}</p>
        </CardBody>
      </Card>
    </>
  );
}

export function BottomBar({ problems, showErr, preview, form, onReview }: {
  problems: Problem[]; showErr: boolean; preview: Preview | undefined; form: BookingForm; onReview: () => void;
}) {
  const v = preview?.vehicle?.name;
  return (
    <div data-testid="bottom-bar"
      className="fixed inset-x-0 bottom-[calc(60px+env(safe-area-inset-bottom))] z-40 flex items-center gap-2.5 border-t border-[var(--haip-border)] bg-[var(--haip-card)] px-4 py-2.5 shadow-[0_-10px_30px_-18px_rgba(0,0,0,.35)] md:bottom-0 md:pb-[calc(10px+env(safe-area-inset-bottom))] lg:hidden">
      <div className="grid min-w-0 flex-1">
        <b className="num font-[family-name:var(--font-display)] text-[20px] leading-tight">{money(preview?.schedule.total ?? 0)}</b>
        <span className={cn("truncate text-[12.5px]", problems.length && showErr ? "font-semibold text-[var(--haip-status-danger-fg)]" : "text-[var(--haip-fg-subtle)]")}>
          {problems.length ? `${problems.length} ${showErr ? "to fix" : "still needed"} · ${problems[0].message}` : `${v ?? ""} · ${span(form.checkIn, form.checkOut)} · ready`}
        </span>
      </div>
      <button type="button" className={BTN_PRIMARY} onClick={onReview}>Review</button>
    </div>
  );
}

export function ReviewSheet({ problems, onJump, onClose, onCreate, creating, ...rest }: SumProps & {
  problems: Problem[]; onJump: (s: Section) => void; onClose: () => void; onCreate: () => void; creating: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.focus();
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);
  const { form, preview } = rest;
  return (
    <div className="fixed inset-0 z-[70] flex items-end justify-center bg-black/45 md:items-center" onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div ref={ref} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby="nb-review-t"
        className="grid max-h-[92vh] w-full content-start gap-3.5 overflow-auto rounded-t-[20px] bg-[var(--haip-app-bg)] px-4 outline-none md:max-h-[88vh] md:w-[min(600px,calc(100vw-48px))] md:rounded-[20px]">
        <div className="sticky top-0 z-[2] flex items-center justify-between gap-2.5 border-b border-[var(--haip-border)] bg-[var(--haip-app-bg)] pb-2 pt-3.5">
          <h2 id="nb-review-t" className="font-[family-name:var(--font-display)] text-[19px] font-semibold">Review booking</h2>
          <button type="button" aria-label="Close" className="grid size-11 place-items-center rounded-xl" onClick={onClose}><X size={18} /></button>
        </div>
        <SummaryRows {...rest} />
        {problems.length > 0 && <StillNeeded problems={problems} showErr onJump={onJump} underline />}
        {form.confirm === "now" && preview?.message_text && (
          <div className="grid gap-1">
            <span className="text-xs font-semibold text-[var(--haip-fg-2)]">WhatsApp to the guest</span>
            <div className="whitespace-pre-wrap rounded-[12px_12px_12px_4px] bg-[var(--haip-status-success-bg)] px-3 py-2.5 text-[14px] leading-relaxed [overflow-wrap:anywhere]">{preview.message_text}</div>
          </div>
        )}
        <div className="sticky bottom-0 z-[2] flex items-center gap-2.5 border-t border-[var(--haip-border)] bg-[var(--haip-app-bg)] pb-[calc(10px+env(safe-area-inset-bottom))] pt-2.5">
          <div className="grid min-w-0 flex-1">
            <b className="num font-[family-name:var(--font-display)] text-[20px]">{money(preview?.schedule.total ?? 0)}</b>
            <span className="truncate text-[12.5px] text-[var(--haip-fg-subtle)]">{preview?.vehicle?.name ?? "No caravan"} · {form.checkIn ? span(form.checkIn, form.checkOut || form.checkIn) : "no dates"}</span>
          </div>
          <button type="button" className={cn(BTN_PRIMARY, "min-h-[50px] text-[15.5px]")} onClick={onCreate} disabled={creating}>{creating ? "Creating…" : "Create booking"}</button>
        </div>
      </div>
    </div>
  );
}

export function Receipt({ r, onAgain }: { r: ComposeReceipt; onAgain: () => void }) {
  return (
    <section aria-live="polite" data-testid="receipt"
      className="haip-card grid max-w-[720px] gap-3.5 p-[18px]">
      <div className="flex items-center gap-3">
        <span className="grid size-11 shrink-0 place-items-center rounded-full bg-primary text-primary-foreground"><Check size={20} /></span>
        <div>
          <h2 className="font-[family-name:var(--font-display)] text-[21px] font-semibold">{r.ref} created on {r.vehicle}</h2>
          <p className={HINT}>{r.guest_name || "Guest"} · {money(r.total)} · here is what HAIP did</p>
        </div>
      </div>
      <ul className="grid gap-2 text-[14.5px]">
        {r.items.map(i => (
          <li key={i.kind + i.text} className="flex items-start gap-2.5" data-done={i.done}>
            <span aria-hidden className={cn("w-4 shrink-0 font-bold", i.done ? "text-primary" : "text-[var(--haip-fg-subtle)]")}>{i.done ? "✓" : "○"}</span>
            <span className="min-w-0 [overflow-wrap:anywhere]"><span className="sr-only">{i.done ? "Done: " : "Not done: "}</span>{i.text}</span>
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap gap-2">
        <Link href={`/dashboard/bookings/${r.booking_id}`} className={BTN_PRIMARY}>Open booking</Link>
        <button type="button" className={BTN} onClick={onAgain}>New booking</button>
      </div>
    </section>
  );
}
