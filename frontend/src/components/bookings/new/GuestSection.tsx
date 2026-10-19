"use client";
// 1 Guest: search a guest or lead, or add a new one by phone (same number = same person, checked as you type), then
// "Start from" one of their saved quotes or from scratch.
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { Plus, Search } from "@/lib/icons";
import { useDebounced } from "@/components/quotes/calc/useDebounced";
import { BTN, BTN_PRIMARY, Field, INPUT } from "@/components/quotes/ui";
import { StatusPill } from "@/components/ui/kit";
import { cn } from "@/lib/utils";
import { day, digits, firstName, masked, money, span } from "./helpers";
import type { BookingForm, ComposeContext, ComposeSetup, GuestCard, QuoteCard, SourceKey } from "./types";
import { HINT, Note, Opt } from "./ui";

interface Props {
  form: BookingForm;
  set: (patch: Partial<BookingForm>) => void;
  setup: ComposeSetup;
  ctx: ComposeContext | undefined;
  onPick: (g: GuestCard) => void;
  onAddNew: (ng: { phone: string; name: string; source: SourceKey }) => void;
  onUseQuote: (q: QuoteCard) => void;
  onScratch: () => void;
  showErr: boolean;
}

function Picked({ form, set, ctx, setup }: Pick<Props, "form" | "set" | "ctx" | "setup">) {
  const g = form.guest;
  const ng = form.newGuest;
  const name = g?.name || ng?.name || "New guest";
  const lead = ctx?.lead ?? g?.open_lead ?? null;
  return (
    <>
      <div className="flex items-start justify-between gap-2.5 rounded-xl border border-[var(--haip-border-strong)] bg-[var(--haip-surface)] px-3 py-2.5">
        <div className="grid min-w-0 flex-1 gap-0.5">
          <b className="text-[16px]">{name}</b>
          <span className={cn(HINT, "num")}>
            {g ? `${masked(g.phone_last4)} · ${g.tag}` : `${masked(digits(ng?.phone ?? "").slice(-4))} · New guest · came from ${setup.sources.find(s => s.value === ng?.source)?.label ?? "—"}`}
          </span>
          {g?.info && <span className={HINT}>{g.info}</span>}
        </div>
        {form.fromLead ? <StatusPill tone="info">From lead</StatusPill>
          : <button type="button" className={BTN} onClick={() => set({ guest: null, newGuest: null, start: null, inquiryId: null })}>Change</button>}
      </div>
      <p className={HINT}>
        {!g ? "HAIP adds this guest and a lead from the source you picked, marked Sold, so the booking counts in source reports."
          : lead ? `This booking is tied to ${firstName(name)}'s open lead (${lead.stage_label}). It moves to Sold when you create it.`
            : "No open lead, so the booking is saved without one."}
      </p>
    </>
  );
}

function NewGuest({ form, set, setup, onPick, onAddNew, showErr }: Props) {
  const phone = useDebounced(form.ng.phone, 300);
  const n = digits(form.ng.phone).length;
  const { data: check } = useQuery<{ valid: boolean; digits: number; existing: GuestCard | null }>({
    queryKey: ["new-booking-phone", phone],
    queryFn: () => api.get("/bookings/compose/guests", { params: { phone } }).then(r => r.data),
    enabled: digits(phone).length >= 10,
  });
  const dup = check?.existing ?? null;
  const badLen = form.ng.phone !== "" && n < 10;
  const ng = (patch: Partial<BookingForm["ng"]>) => set({ ng: { ...form.ng, ...patch } });
  const add = () => {
    if (n < 10 || (check && !check.valid)) return;
    if (!form.ng.source) return;
    onAddNew({ phone: form.ng.phone, name: form.ng.name.trim(), source: form.ng.source as SourceKey });
  };
  return (
    <div className="grid gap-2.5 rounded-xl border border-[var(--haip-border-strong)] bg-[var(--haip-surface)] p-3">
      <h3 className="text-[15px] font-semibold">Add a new guest</h3>
      <div className="grid gap-2.5 sm:grid-cols-3">
        <Field label="Mobile number (needed)" htmlFor="nb-ng-phone">
          <input id="nb-ng-phone" className={cn(INPUT, "num", (dup || (badLen && showErr)) && "border-[var(--haip-status-danger-fg)]")} inputMode="tel"
            autoComplete="off" placeholder="98765 43210" value={form.ng.phone} onChange={e => ng({ phone: e.target.value })} />
        </Field>
        <Field label="Name" htmlFor="nb-ng-name">
          <input id="nb-ng-name" className={INPUT} placeholder="As the guest gave it" value={form.ng.name} onChange={e => ng({ name: e.target.value })} />
        </Field>
        <Field label="Came from" htmlFor="nb-ng-src">
          <select id="nb-ng-src" className={INPUT} value={form.ng.source} onChange={e => ng({ source: e.target.value as SourceKey })}>
            <option value="">Pick one</option>
            {setup.sources.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
          </select>
        </Field>
      </div>
      {dup ? (
        <Note tone="warn" actions={<button type="button" className={BTN} onClick={() => onPick(dup)}>Use {dup.name || "this guest"}</button>}>
          <b>{dup.name || "A guest"}</b> already has this number ({dup.tag}). Same number = same person, so HAIP will not make a second guest.
        </Note>
      ) : badLen ? (
        <p className="text-[13.5px] font-semibold text-[var(--haip-status-danger-fg)]">Enter a 10-digit mobile number. {n} digit{n === 1 ? "" : "s"} so far.</p>
      ) : check && !check.valid ? (
        <p className="text-[13.5px] font-semibold text-[var(--haip-status-danger-fg)]">That is not a usable mobile number.</p>
      ) : <p className={HINT}>We check the number against every guest, so nobody is added twice.</p>}
      {n >= 10 && !form.ng.source && <p className={HINT}>Pick where the guest came from, so reports count it right.</p>}
      <div className="flex flex-wrap gap-2">
        <button type="button" className={BTN_PRIMARY} disabled={!!dup || n < 10 || !form.ng.source} onClick={add}>Add guest</button>
        <button type="button" className={BTN} onClick={() => set({ adding: false })}>Back to search</button>
      </div>
    </div>
  );
}

function SearchBox({ form, set, onPick }: Props) {
  const q = useDebounced(form.guestQ.trim(), 250);
  const { data, isError, isFetching, refetch } = useQuery<{ results: GuestCard[]; recent: boolean }>({
    queryKey: ["new-booking-guests", q],
    queryFn: () => api.get("/bookings/compose/guests", { params: { q } }).then(r => r.data),
  });
  const qd = digits(form.guestQ);
  const hits = data?.results ?? [];
  return (
    <>
      <label className="relative block">
        <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--haip-fg-subtle)]" />
        <input type="search" className={cn(INPUT, "pl-9")} placeholder="Search guest or lead: name or phone" aria-label="Search guest"
          autoComplete="off" value={form.guestQ} onChange={e => set({ guestQ: e.target.value })} />
      </label>
      <div className="grid gap-1.5" aria-busy={isFetching}>
        {!q && hits.length > 0 && <span className={HINT}>Recent</span>}
        {isError && <Note tone="bad" actions={<button type="button" className={BTN} onClick={() => refetch()}>Try again</button>}>Couldn&apos;t search guests.</Note>}
        {hits.map(g => (
          <button key={g.guest_id} type="button" onClick={() => onPick(g)}
            className="flex min-h-[52px] w-full flex-wrap items-center justify-between gap-x-2.5 gap-y-0.5 rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 py-2 text-left text-[14px] hover:border-primary">
            <b>{g.name || "Unnamed guest"}</b>
            <span className={cn(HINT, "num")}>{masked(g.phone_last4)}</span>
            <span className="w-full text-[12.5px] text-[var(--haip-fg-subtle)]">
              {g.tag}{g.quotes_count ? ` · ${g.quotes_count} saved quote${g.quotes_count > 1 ? "s" : ""}` : ""}
            </span>
          </button>
        ))}
        {q && !isFetching && !isError && hits.length === 0 && <p className={HINT}>No guest or lead matches “{form.guestQ.trim()}”.</p>}
        {!q && !isFetching && !isError && hits.length === 0 && <p className={HINT}>Type a name or the last digits of a phone number.</p>}
      </div>
      <button type="button" className={cn(BTN, "justify-self-start text-primary")}
        onClick={() => set({ adding: true, ng: { phone: qd.length >= 3 ? qd : "", name: qd.length >= 3 ? "" : form.guestQ.trim(), source: "" } })}>
        <Plus size={15} />Add new guest{qd.length >= 3 ? ` with ${qd}` : ""}
      </button>
    </>
  );
}

function Quotes({ form, ctx, onUseQuote, onScratch }: Props) {
  const name = form.guest?.name || form.newGuest?.name || "This guest";
  const qs = ctx?.quotes ?? [];
  if (!form.guest) return null;
  if (!qs.length) return <p className={HINT}>{name} has no saved quotes, so fill the trip below.</p>;
  return (
    <div className="grid gap-1.5" role="radiogroup" aria-label="Start from">
      <span className="text-xs font-semibold text-[var(--haip-fg-2)]">Start from</span>
      {qs.map(q => q.booked || !q.usable ? (
        <div key={q.quote_id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-[var(--haip-border)] px-3 py-2 opacity-70">
          <span className="grid min-w-0 flex-1 gap-px text-[14px]">
            <b>{q.number} · {money(q.total)}</b>
            <span className="text-[12.5px] text-[var(--haip-fg-subtle)]">{q.label}{q.check_in ? ` · ${span(q.check_in, q.check_out ?? q.check_in)}` : ""}</span>
            <span className="text-[12.5px] text-[var(--haip-fg-subtle)]">
              {q.booked ? `${q.sent}. Booking ${q.booked.ref} was made from it${q.booked.automatic ? " automatically" : ""}.` : q.why_not}
            </span>
          </span>
          {q.booked && <Link className={BTN} href={`/dashboard/bookings/${q.booked.booking_id}`}>Open {q.booked.ref}</Link>}
        </div>
      ) : (
        <Opt key={q.quote_id} on={form.start === q.quote_id} onClick={() => onUseQuote(q)} testId={`quote-${q.quote_id}`}
          title={<>{q.number} · {money(q.total)} {q.latest && <StatusPill tone="info">Latest</StatusPill>}</>}
          sub={<>{q.label} · {day(q.check_in)} → {day(q.check_out)}{q.guests ? ` · ${q.guests} guests` : ""}
            {q.addons_count ? ` · ${q.addons_count} add-on${q.addons_count > 1 ? "s" : ""}` : ""}<br />{q.sent}</>} />
      ))}
      <Opt on={form.start === "scratch"} onClick={onScratch} title="Start from scratch"
        sub={ctx?.trip?.check_in ? "Dates and guests come from the lead; you pick the package and price." : "Fill the trip and price yourself."} />
    </div>
  );
}

export function GuestSection(props: Props) {
  const { form } = props;
  const picked = !!(form.guest || form.newGuest);
  return (
    <>
      {picked ? <Picked {...props} /> : form.adding ? <NewGuest {...props} /> : <SearchBox {...props} />}
      <Quotes {...props} />
    </>
  );
}
