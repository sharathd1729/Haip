"use client";
// The quote as the guest would get it, always current: lines, subtotal, GST, total, advance, tolls at actuals, reseller commission,
// refusals with one-click fixes, the fallback option, saving to a lead and sending it with a payment link per option (then the
// journey: paid -> booking -> invoice). Every number comes from POST /quotes/preview.
import { Loader2, Send } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { Card, CardBody, CardHeader, StatusPill } from "@/components/ui/kit";
import { dayLabel, entryName, fixAction, money } from "@/app/dashboard/quotes/quoteHelpers";
import type { SendGate } from "@/app/dashboard/quotes/sendHelpers";
import type { Catalog, IssueResult, Journey, LeadHit, OptionForm, PricedOption, Preview } from "@/app/dashboard/quotes/types";
import { LeadPicker } from "./LeadPicker";
import { QuoteJourney } from "./QuoteJourney";
import { BTN, BTN_PRIMARY, Callout, Field, INPUT } from "./ui";

function Row({ label, detail, amount, strong, muted }: { label: string; detail?: string; amount: string; strong?: boolean; muted?: boolean }) {
  return (
    <div className={cn("flex items-start gap-3 py-2", strong && "border-t border-[var(--haip-border)] pt-3")}>
      <span className="min-w-0 flex-1">
        <span className={cn("block text-[13.5px]", strong ? "font-bold" : "font-medium")}>{label}</span>
        {detail && <span className="block text-[12px] leading-snug text-[var(--haip-fg-subtle)]">{detail}</span>}
      </span>
      <span className={cn("num shrink-0 text-right tabular-nums", strong ? "text-[16px] font-bold" : "text-[13.5px]", muted && "text-[var(--haip-fg-subtle)]")}>{amount}</span>
    </div>
  );
}

export function PriceLines({ q }: { q: PricedOption }) {
  const balance = q.total && q.advance ? String(Number(q.total) - Number(q.advance)) : null;
  return (
    <div className="divide-y divide-[var(--haip-border)]">
      {q.lines.map((l, i) => {
        const minus = l.amount.startsWith("-");
        return <Row key={`${l.label}-${i}`} label={l.label} detail={l.detail} amount={minus ? `- ${money(l.amount.slice(1))}` : money(l.amount)} />;
      })}
      <Row label="Subtotal" amount={money(q.taxable ?? q.subtotal)} />
      <Row label={`GST ${Number(q.gst_percent ?? 0)}%`} detail="Rate from the package; to be confirmed" amount={money(q.gst)} />
      <Row label="Total" amount={money(q.total)} strong />
      {q.advance ? <Row label={`Advance ${Number(q.advance_percent ?? 0)}%`} detail={balance ? `Balance ${money(balance)} before travel begins` : undefined} amount={money(q.advance)} />
        : <Row label="Advance" detail="No payment terms are published; the team confirms the advance." amount="—" muted />}
      {q.at_actuals.map(a => <Row key={a} label={a} detail="Billed at actuals, not in the total." amount="Extra" muted />)}
      {q.commission && (
        <Row label={`Reseller commission ${Number(q.commission.percent)}%`} amount={money(q.commission.amount)}
          detail={`On ${money(q.commission.on_amount)} before tax. Net to the business ${money(q.commission.net_to_business)} + GST.`} />
      )}
    </div>
  );
}

export interface SentState { quoteId: string; journey: Journey; notice: string | null }

export function QuoteCard({ catalog, form, preview, loading, failed, onFix, fallbackKey, onFallback, lead, onLead, nextAt, onNextAt, onSave, saving, saved,
  gate, onSend, sending, sent, onNewQuote }: {
  catalog: Catalog; form: OptionForm; preview: Preview | undefined; loading: boolean; failed: boolean;
  onFix: (patch: Partial<OptionForm>) => void;
  fallbackKey: string; onFallback: (k: string) => void;
  lead: LeadHit | null; onLead: (l: LeadHit | null) => void;
  nextAt: string; onNextAt: (v: string) => void;
  onSave: () => void; saving: boolean; saved: IssueResult | null;
  gate: SendGate; onSend: () => void; sending: boolean; sent: SentState | null; onNewQuote: () => void;
}) {
  const q = preview?.primary;
  const f = preview?.fallback;
  const ok = q?.status === "ok";
  const vehicle = q?.availability.find(v => v.property_id === form.vehicle_property_id && v.status === "available")
    ?? (form.vehicle_property_id ? null : q?.availability.find(v => v.status === "available"));
  const fix = q && q.status === "refused" ? fixAction(q.fix, catalog) : null;
  const canSave = !!preview?.can_save && !!lead && !!nextAt && catalog.permissions.can_quote;
  const otherRoutes = catalog.destinations.filter(d => d.key !== form.destination_key);

  return (
    <Card>
      <CardHeader title="Quote" actions={loading && !q ? <Loader2 size={16} className="animate-spin text-[var(--haip-fg-subtle)]" />
        : ok ? <span className="num text-[20px] font-bold tabular-nums">{money(q!.total)}</span> : <StatusPill tone="danger">Can&apos;t price yet</StatusPill>} />
      <CardBody className="space-y-3">
        {failed && !q && <Callout tone="danger">Couldn&apos;t price this. Check your connection and change any field to try again.</Callout>}
        {q && (
          <>
            <div className="flex flex-wrap items-center gap-1.5">
              {q.package_name && <StatusPill tone="brand">{q.package_name}{q.level ? ` · ${money(q.level)}` : ""}</StatusPill>}
              {form.channel === "reseller" && <StatusPill tone="info">Reseller</StatusPill>}
              {vehicle ? <StatusPill tone="success">{vehicle.property_name}</StatusPill> : q.availability.length > 0 && <StatusPill tone="danger">No caravan free</StatusPill>}
              <span className="text-[12.5px] text-[var(--haip-fg-subtle)]">
                {q.destination?.name ?? "No route"} · {dayLabel(q.start_date)} to {dayLabel(q.end_date)} · {form.adults + form.children} guests
                {q.days ? ` · ${q.days} day${q.days === 1 ? "" : "s"} billed` : ""}
              </span>
            </div>
            {q.status === "refused" && (
              <Callout tone="danger" action={fix && <button type="button" className={BTN} onClick={() => onFix(fix.patch)}>{fix.label}</button>}>{q.message}</Callout>
            )}
            {q.warnings.map(w => <Callout key={w} tone="warning">{w}</Callout>)}
            {ok ? <PriceLines q={q} /> : <p className="text-[13px] text-[var(--haip-fg-subtle)]">No price until the trip can run. Fix the item above.</p>}
            {ok && q.valid_until && <p className="text-xs text-[var(--haip-fg-subtle)]">Valid until {dayLabel(q.valid_until)}. Prices and the km rate are locked when the quote is saved.</p>}
          </>
        )}

        {sent ? (
          <QuoteJourney quoteId={sent.quoteId} initial={sent.journey} notice={sent.notice} onNewQuote={onNewQuote} />
        ) : (
          <>
            <Field label="Fallback option" htmlFor="quote-fallback"
              hint={!fallbackKey ? "The playbook asks for one recommendation and one fallback."
                : !f ? "Pricing the fallback…"
                : f.status === "ok" ? `Option 2: ${f.destination?.name ?? ""}, ${f.package_name}, ${money(f.total)} incl. GST. Priced on its own.`
                : `Option 2 can't be priced: ${f.message}`}>
              <select id="quote-fallback" value={fallbackKey} onChange={e => onFallback(e.target.value)} className={INPUT}>
                <option value="">None</option>
                {otherRoutes.map(d => <option key={d.key} value={d.key}>{entryName(d)}</option>)}
              </select>
            </Field>
            <Field label="Quote for"><LeadPicker value={lead} onChange={onLead} /></Field>
            <Field label="Next step" htmlFor="quote-next" hint="Becomes the lead's follow-up, so it shows on My day.">
              <input id="quote-next" type="datetime-local" value={nextAt} onChange={e => onNextAt(e.target.value)} className={INPUT} />
            </Field>

            {preview && preview.send_blockers.length > 0 && ok && (
              <div className="text-xs text-[var(--haip-fg-subtle)]">
                <p className="font-semibold text-[var(--haip-fg-2)]">Before sending</p>
                <ul className="list-disc pl-4">{preview.send_blockers.map(b => <li key={b}>{b}</li>)}</ul>
              </div>
            )}
            <div className="flex flex-wrap gap-2">
              <button type="button" className={BTN_PRIMARY} disabled={!canSave || saving} onClick={onSave}>
                {saving ? <Loader2 size={14} className="animate-spin" /> : "Save to lead"}
              </button>
              <button type="button" className={BTN} disabled={!gate.canSend || sending || saving} onClick={onSend} aria-describedby="quote-send-why">
                {sending ? <Loader2 size={14} className="animate-spin" /> : <Send size={13} />} Send quote + payment link
              </button>
            </div>
            <p className="text-xs text-[var(--haip-fg-subtle)]">
              {!catalog.permissions.can_quote ? "Your role can look at prices but not save quotes."
                : !lead ? "Pick the lead to save this quote to." : !nextAt ? "Set a dated next step to save." : preview?.save_blockers[0] ?? ""}
            </p>
            <p id="quote-send-why" className="text-xs text-[var(--haip-fg-subtle)]">
              {gate.canSend ? gate.note ?? "Sends the approved WhatsApp template with a Razorpay link for each option's advance." : `To send: ${gate.reason}`}
            </p>
            {saved && (
              <Callout tone="success">
                Saved to {lead?.guest_name ?? "the lead"}: {money(saved.quotes[0]?.amount)}
                {saved.quotes[1] ? `, option 2 ${money(saved.quotes[1].amount)}` : ""}.{saved.next_step ? " Follow-up set." : ""}
              </Callout>
            )}
          </>
        )}
      </CardBody>
    </Card>
  );
}
