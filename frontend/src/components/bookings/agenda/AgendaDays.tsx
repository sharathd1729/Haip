"use client";
// Day rows: each day's check-ins and check-outs in time order. A row: what happens (tag), who, when, which vehicle, how many,
// the trip, the one money fact that matters (collect / return the deposit / overdue), and Call / WhatsApp.
import { MessageCircle, Phone } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { StatusPill } from "@/components/ui/kit";
import { clock, dayLabel, groupByDay, guestName, moneyChip, type AgendaEvent, type AgendaRow } from "@/lib/bookingAgenda";

const TAG: Record<AgendaEvent["kind"], { label: string; cls: string }> = {
  in: { label: "Check-in", cls: "bg-[var(--haip-status-success-bg)] text-[var(--haip-status-success-fg)]" },
  out: { label: "Check-out", cls: "bg-[var(--haip-status-info-bg)] text-[var(--haip-status-info-fg)]" },
  cancelled: { label: "Cancelled", cls: "bg-[var(--haip-status-danger-bg)] text-[var(--haip-status-danger-fg)]" },
};
const SLOT_TAG: Record<number, string> = {
  0: "bg-[var(--haip-status-warning-bg)] text-[var(--haip-status-warning-fg)]",
  1: "bg-[var(--haip-cal-vehicle-1)] text-[var(--haip-cal-vehicle-fg)]",
  2: "bg-[var(--haip-cal-vehicle-2)] text-[var(--haip-cal-vehicle-fg)]",
};
const iconBtn = "flex size-11 shrink-0 items-center justify-center rounded-xl text-[var(--haip-fg-2)] hover:bg-[var(--haip-surface)] disabled:opacity-40";

export function VehicleTag({ name, slot }: { name: string | null | undefined; slot: number }) {
  return <span className={cn("inline-flex items-center rounded-lg px-2 py-px text-[12.5px] font-bold", SLOT_TAG[slot] ?? SLOT_TAG[1])}>{name ?? "No vehicle"}</span>;
}

function EventRow({ e, today, selected, slot, onOpen, onCall, onWhatsApp }: {
  e: AgendaEvent; today: string; selected: boolean; slot: number;
  onOpen: (id: string) => void; onCall: (r: AgendaRow) => void; onWhatsApp: (id: string) => void;
}) {
  const r = e.row;
  const name = guestName(r);
  const chip = moneyChip(e.kind, r, today);
  const time = clock(e.time);
  const guests = r.adults + r.children;
  return (
    <div className={cn("flex min-w-0 items-center gap-2 rounded-[14px] border bg-[var(--haip-card)] py-1 pl-3 pr-1",
      selected ? "border-primary ring-1 ring-inset ring-primary" : "border-[var(--haip-border)]")}>
      <button type="button" onClick={() => onOpen(r.id)} aria-current={selected ? "true" : undefined}
        className="grid min-h-11 min-w-0 flex-1 gap-0.5 py-2 text-left" aria-label={`${TAG[e.kind].label}: ${name}${time ? ` at ${time}` : ""}`}>
        <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[14.5px] font-bold text-[var(--haip-fg)]">
          <span className={cn("rounded-md px-1.5 py-px text-[11.5px] font-extrabold uppercase tracking-[0.03em]", TAG[e.kind].cls)}>{TAG[e.kind].label}</span>
          <span className={cn("min-w-0 [overflow-wrap:anywhere]", e.kind === "cancelled" && "text-[var(--haip-fg-subtle)] line-through")}>{name}</span>
          {e.stayingNow && <span className="text-[12.5px] font-medium text-[var(--haip-fg-subtle)]">staying now</span>}
        </span>
        <span className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[13px] text-[var(--haip-fg-subtle)]">
          {time && <span className="tabular-nums">{time} ·</span>}
          <VehicleTag name={r.property?.name} slot={slot} />
          <span>· {guests} guest{guests === 1 ? "" : "s"}</span>
          {r.trip && <span className="min-w-0 [overflow-wrap:anywhere]">· {r.trip}</span>}
        </span>
        {chip && <span><StatusPill tone={chip.tone}>{chip.label}</StatusPill></span>}
      </button>
      <div className="flex shrink-0 gap-0.5">
        <button type="button" className={iconBtn} aria-label={`Call ${name}`} disabled={!r.main_guest?.phone} onClick={() => onCall(r)}><Phone size={18} /></button>
        <button type="button" className={iconBtn} aria-label={`WhatsApp ${name}`} disabled={!r.main_guest?.phone} onClick={() => onWhatsApp(r.id)}><MessageCircle size={18} /></button>
      </div>
    </div>
  );
}

export function AgendaDays({ events, today, selectedId, slotOf, onOpen, onCall, onWhatsApp }: {
  events: AgendaEvent[]; today: string; selectedId?: string; slotOf: (r: AgendaRow) => number;
  onOpen: (id: string) => void; onCall: (r: AgendaRow) => void; onWhatsApp: (id: string) => void;
}) {
  return (
    <div className="grid gap-2" aria-label="Check-ins and check-outs by day">
      {groupByDay(events).map(d => {
        const l = dayLabel(d.day, today);
        const isToday = d.day === today;
        return (
          <section key={d.day} className="grid grid-cols-[64px_minmax(0,1fr)] gap-2.5 md:grid-cols-[84px_minmax(0,1fr)]" aria-label={`${l.top} ${l.day} ${l.month}`}>
            <div className={cn("pt-2 text-center", isToday ? "text-[var(--haip-accent-ink)]" : "text-[var(--haip-fg-subtle)]")}>
              <span className="block text-[12px] font-bold uppercase">{l.top}</span>
              <b className={cn("block font-[family-name:var(--font-display)] text-[24px] leading-none", isToday ? "text-[var(--haip-accent-ink)]" : "text-[var(--haip-fg)]")}>{l.day}</b>
              <span className="block text-[12px] font-bold uppercase">{l.month}</span>
            </div>
            <div className="grid min-w-0 gap-1.5">
              {d.events.map(e => (
                <EventRow key={e.key} e={e} today={today} selected={e.row.id === selectedId} slot={slotOf(e.row)}
                  onOpen={onOpen} onCall={onCall} onWhatsApp={onWhatsApp} />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
