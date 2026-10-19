"use client";
// The CRM Bookings list (layout A · Cards by date): one card per booking under its check-in day. A card: guest + status, caravan,
// the stay in one line, guests, how much is paid, what is due (or overdue), and Call / WhatsApp / Collect.
// The day groups themselves flow across columns (mock-up A ".groups"): each group is its heading with its cards stacked, in
// chronological order left to right, then down. One column on a phone, three on a desktop, two while the booking pane is open.
import { CreditCard, MessageCircle, Phone } from "@/lib/icons";
import { cn, formatINR } from "@/lib/utils";
import { StatusPill } from "@/components/ui/kit";
import { VehicleTag } from "@/components/bookings/agenda/AgendaDays";
import { STATUS_STYLE, STATUS_TONE } from "@/lib/bookings";
import { guestName, type AgendaRow, type Segment } from "@/lib/bookingAgenda";
import { groupCards, paidPct, payState, stayLine } from "@/lib/bookingCards";

const action = "flex min-h-12 items-center justify-center gap-1.5 whitespace-nowrap px-1.5 text-[13.5px] font-semibold disabled:cursor-default disabled:text-[var(--haip-fg-subtle)] hover:enabled:bg-[var(--haip-surface)]";

function BookingCard({ r, today, selected, slot, canCollect, onOpen, onCall, onWhatsApp, onCollect }: {
  r: AgendaRow; today: string; selected: boolean; slot: number; canCollect: boolean;
  onOpen: (id: string) => void; onCall: (r: AgendaRow) => void; onWhatsApp: (id: string) => void; onCollect: (id: string) => void;
}) {
  const name = guestName(r);
  const cancelled = r.raw_status === "cancelled";
  const pay = payState(r, today);
  const guests = r.adults + r.children;
  const st = STATUS_STYLE[r.raw_status] ?? STATUS_STYLE.confirmed;
  return (
    <article className={cn("haip-card flex min-w-0 flex-col overflow-hidden", selected && "ring-2 ring-inset ring-primary")} data-booking={r.id}>
      <button type="button" onClick={() => onOpen(r.id)} aria-current={selected ? "true" : undefined} aria-label={`Open ${name}, booking ${r.external_id}`}
        className="grid gap-2 px-4 pb-2.5 pt-3.5 text-left">
        <span className="flex items-start justify-between gap-2">
          <span className="min-w-0 text-[16px] font-bold text-[var(--haip-fg)] [overflow-wrap:anywhere]">{name}</span>
          <StatusPill tone={STATUS_TONE[r.raw_status] ?? "info"}>{st.label}</StatusPill>
        </span>
        <span className="flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[14px] text-[var(--haip-fg-2)]">
          <VehicleTag name={r.property?.name} slot={slot} />
          <span>{stayLine(r)}</span>
          <span>{guests} guest{guests === 1 ? "" : "s"}</span>
        </span>
        {r.trip && <span className="text-[13px] text-[var(--haip-fg-subtle)] [overflow-wrap:anywhere]">{r.trip}</span>}
        {cancelled ? (
          <span className="flex items-center justify-between gap-2 text-[13.5px]">
            <span className="text-[var(--haip-fg-subtle)]">{r.total_paid > 0 ? `${formatINR(r.total_paid)} was paid` : "Nothing was paid"}</span>
            <s className="tabular-nums text-[var(--haip-fg-subtle)]" data-testid="cancelled-total">{formatINR(r.total)}</s>
          </span>
        ) : (
          <>
            <progress value={paidPct(r)} max={100} aria-label={`${paidPct(r)}% paid`}
              className="h-1.5 w-full appearance-none overflow-hidden rounded-full bg-[var(--haip-border)] [&::-moz-progress-bar]:bg-primary [&::-webkit-progress-bar]:bg-[var(--haip-border)] [&::-webkit-progress-value]:bg-primary" />
            <span className="flex flex-wrap items-center justify-between gap-2 text-[13.5px]">
              <span className="flex flex-wrap items-center gap-1.5">
                {pay && <StatusPill tone={pay.tone}>{pay.pill}</StatusPill>}
                {pay?.text && <span className={cn("tabular-nums", pay.tone === "danger" && pay.due > 0 ? "font-semibold text-[var(--haip-status-danger-fg)]" : "text-[var(--haip-fg-subtle)]")}>{pay.text}</span>}
              </span>
              <strong className="tabular-nums text-[var(--haip-fg)]">{formatINR(r.total)}</strong>
            </span>
          </>
        )}
      </button>
      <div className="mt-auto grid grid-cols-3 border-t border-[var(--haip-border)]">
        <button type="button" className={cn(action, "text-primary")} disabled={!r.main_guest?.phone} onClick={() => onCall(r)} aria-label={`Call ${name}`}>
          <Phone size={15} /> Call
        </button>
        <button type="button" className={cn(action, "border-l border-[var(--haip-border)] text-primary")} disabled={!r.main_guest?.phone} onClick={() => onWhatsApp(r.id)} aria-label={`WhatsApp ${name}`}>
          <MessageCircle size={15} /> WhatsApp
        </button>
        <button type="button" className={cn(action, "border-l border-[var(--haip-border)] text-[var(--haip-accent-ink)]")}
          disabled={!pay || pay.due <= 0 || !canCollect} onClick={() => onCollect(r.id)} aria-label={pay && pay.due > 0 ? `Collect from ${name}` : `${name}: nothing to collect`}>
          <CreditCard size={15} /> {pay && pay.due > 0 ? "Collect" : cancelled ? "Cancelled" : "Paid"}
        </button>
      </div>
    </article>
  );
}

export function BookingCards({ rows, segment, today, selectedId, paneOpen, canCollect, slotOf, onOpen, onCall, onWhatsApp, onCollect }: {
  rows: AgendaRow[]; segment: Segment; today: string; selectedId?: string; paneOpen: boolean; canCollect: boolean;
  slotOf: (r: AgendaRow) => number;
  onOpen: (id: string) => void; onCall: (r: AgendaRow) => void; onWhatsApp: (id: string) => void; onCollect: (id: string) => void;
}) {
  return (
    <div data-testid="card-groups" data-pane-open={paneOpen ? "true" : undefined}
      className={cn("grid items-start gap-x-3 gap-y-4",
        // Columns of at least 330px (one on a phone); with the pane open each is also at least 34% wide, so never more than two.
        paneOpen ? "grid-cols-[repeat(auto-fill,minmax(min(100%,max(330px,34%)),1fr))]" : "grid-cols-[repeat(auto-fill,minmax(min(100%,330px),1fr))]")}>
      {groupCards(rows, segment, today).map(g => (
        <section key={g.key} className="grid min-w-0 gap-2" aria-label={g.title}>
          <h3 className={cn("flex flex-wrap items-baseline gap-x-2 px-0.5 pt-1 text-[12.5px] font-bold uppercase tracking-[0.04em]",
            g.key === today ? "text-[var(--haip-accent-ink)]" : "text-[var(--haip-fg-subtle)]")}>
            {g.title} <span className="font-medium normal-case tracking-normal">· {g.hint}</span>
          </h3>
          <div className="grid gap-2.5">
            {g.rows.map(r => (
              <BookingCard key={r.id} r={r} today={today} selected={r.id === selectedId} slot={slotOf(r)} canCollect={canCollect}
                onOpen={onOpen} onCall={onCall} onWhatsApp={onWhatsApp} onCollect={onCollect} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
