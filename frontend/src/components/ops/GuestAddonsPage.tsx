"use client";
// The guest's add-ons page (no login), opened from a private link /r/addons/<token> (design B, "offer cards + receipt",
// picked by the owner 8 Nov 2026). The stay, the property's add-ons at their published prices as "passes" (HAIP's own icons
// and card), a receipt, ONE Pay button that opens a Razorpay link. Items the team must OK first (late check-out, extra night,
// a cook...) are sent as a request; the link comes on WhatsApp after a person approves. Backend: GET/POST
// /api/v1/public/addons/{token}[/orders] (services/guest_addons.py). Phone first: 16px+ text, 44px+ targets.
import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { cn } from "@/lib/utils";
import {
  daysToGo, greeting, inr, payLabel, quantityWord, receipt,
  type AddonOffer, type AddonOrder, type AddonsView, type Picks,
} from "@/lib/guestAddons";
import { AddonIcon, CalendarIcon, ClockIcon, LockIcon, MinusIcon, PlusIcon, TickIcon, iconFor } from "./addonIcons";
import s from "./GuestAddons.module.css";

const _raw = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
const API = _raw.endsWith("/api/v1") ? _raw : `${_raw}/api/v1`;
const display = "font-[family-name:var(--font-display)] tracking-[-0.02em]";
const day = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" });
const localToday = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

const ORDER_WORDS: Record<AddonOrder["status"], { label: string; tone: string }> = {
  awaiting_approval: { label: "Waiting for the team", tone: "bg-[var(--haip-status-warning-bg)] text-[var(--haip-status-warning-fg)]" },
  awaiting_payment: { label: "Ready to pay", tone: "bg-[var(--haip-accent-light)] text-[var(--haip-accent-ink)]" },
  paid: { label: "Paid", tone: "bg-[var(--haip-chip-bg)] text-[var(--haip-chip-fg)]" },
  declined: { label: "Not available", tone: "bg-[var(--haip-olive-bg)] text-[var(--haip-fg-subtle)]" },
  cancelled: { label: "Cancelled", tone: "bg-[var(--haip-olive-bg)] text-[var(--haip-fg-subtle)]" },
};

function Stepper({ o, q, onChange }: { o: AddonOffer; q: number; onChange: (n: number) => void }) {
  const step = "inline-flex size-11 items-center justify-center rounded-full border border-[var(--haip-btn-secondary-border)] bg-[var(--haip-card)] text-[var(--haip-primary)] disabled:opacity-40";
  return (
    <div className="flex items-center justify-between border-t border-[var(--haip-band-bg)] pt-3">
      <p className="text-[15px] font-semibold text-[var(--haip-fg)]">{o.price_type === "per_night" ? "Nights" : o.price_type === "per_person" ? "People" : "How many"}</p>
      <div className="flex items-center gap-2.5">
        <button type="button" className={cn(step, s.press)} aria-label={`One less: ${o.name}`} disabled={q <= 1} onClick={() => onChange(q - 1)}>
          <MinusIcon className="size-[18px]" /></button>
        <span className="min-w-6 text-center text-[17px] font-bold tabular-nums" aria-live="polite">{q}</span>
        <button type="button" className={cn(step, s.press)} aria-label={`One more: ${o.name}`} disabled={q >= o.max_quantity} onClick={() => onChange(q + 1)}>
          <PlusIcon className="size-[18px]" /></button>
      </div>
    </div>
  );
}

function AddButton({ o, added, onToggle, onDark = false }: { o: AddonOffer; added: boolean; onToggle: () => void; onDark?: boolean }) {
  const idle = onDark ? "border-[var(--haip-card)] bg-[var(--haip-card)] text-[var(--haip-nav-bg)]"
    : "border-[var(--haip-btn-secondary-border)] bg-[var(--haip-card)] text-[var(--haip-primary)]";
  const on = onDark ? "border-[var(--haip-tile-fg)] bg-[var(--haip-tile-fg)] text-[var(--haip-nav-bg)]"
    : "border-[var(--haip-primary)] bg-[var(--haip-primary)] text-[var(--haip-on-accent)]";
  const verb = o.needs_approval ? ["Request", "Requested"] : ["Add", "Added"];
  return (
    <button type="button" aria-pressed={added} onClick={onToggle}
      className={cn("inline-flex min-h-12 w-full items-center justify-center gap-2 rounded-xl border text-[16px] font-semibold", s.press, added ? on : idle)}>
      {added && <TickIcon key="tick" className={cn("size-5", s.tick)} />}
      {added ? verb[1] : verb[0]}
    </button>
  );
}

function ConfirmNote({ dark = false }: { dark?: boolean }) {
  return (
    <p className={cn("inline-flex items-center gap-1.5 self-start rounded-full px-2.5 py-1 text-[13px] font-semibold",
      dark ? "text-[var(--haip-nav-fg)]" : "bg-[var(--haip-status-warning-bg)] text-[var(--haip-status-warning-fg)]")}>
      <ClockIcon className="size-[15px]" />We confirm this first, then send your link
    </p>
  );
}

function Pass({ o, q, onToggle, onQty }: { o: AddonOffer; q: number | undefined; onToggle: () => void; onQty: (n: number) => void }) {
  const added = q !== undefined;
  return (
    <article className={s.pass} data-on={added} data-off={!o.available}>
      <div className="flex items-start gap-3.5 p-[18px]">
        <div className={cn(s.tile, s.spark)}><AddonIcon kind={iconFor(o)} /></div>
        <div className="min-w-0 flex-1">
          <h3 className={cn("text-[17px] font-semibold", o.available ? "text-[var(--haip-fg)]" : "text-[var(--haip-fg-subtle)]")}>{o.name}</h3>
          {o.description && <p className="mt-0.5 text-[14px] leading-snug text-[var(--haip-fg-muted)]">{o.description}</p>}
        </div>
        <div className="text-right">
          <p className={cn(display, "text-[19px] font-bold text-[var(--haip-nav-bg)]")}>{inr(o.price)}</p>
          <p className="text-[13px] text-[var(--haip-fg-subtle)]">{o.unit}</p>
        </div>
      </div>
      {o.available ? (
        <>
          {(o.needs_approval || (added && o.max_quantity > 1)) && (
            <div className="flex flex-col gap-3 px-[18px] pb-3.5">
              {o.needs_approval && <ConfirmNote />}
              {added && o.max_quantity > 1 && <Stepper o={o} q={q} onChange={onQty} />}
            </div>
          )}
          <div className={s.perf} />
          <div className="px-[18px] pb-[18px] pt-3.5"><AddButton o={o} added={added} onToggle={onToggle} /></div>
        </>
      ) : (
        <p className="px-[18px] pb-[18px] text-[14px] text-[var(--haip-fg-subtle)]">Not available: {o.unavailable_reason}</p>
      )}
    </article>
  );
}

function Featured({ o, q, onToggle, onQty }: { o: AddonOffer; q: number | undefined; onToggle: () => void; onQty: (n: number) => void }) {
  const added = q !== undefined;
  return (
    <section className="flex flex-col gap-4 rounded-2xl bg-[var(--haip-tile-bg)] p-5 text-[var(--haip-nav-fg)]" aria-label={o.name}>
      <div className="flex items-start justify-between gap-3">
        <div className={cn(s.tile, s.tileDark, s.spark)}><AddonIcon kind={iconFor(o)} /></div>
        <div className="text-right">
          <p className={cn(display, "text-[26px] font-bold text-[var(--haip-on-accent)]")}>{inr(o.price)}</p>
          <p className="text-[14px]">{o.unit}</p>
        </div>
      </div>
      <div className="flex flex-col gap-1.5">
        <h2 className={cn(display, "text-[22px] font-semibold leading-tight text-[var(--haip-on-accent)]")}>{o.name}</h2>
        {o.description && <p className="text-[15px] leading-snug">{o.description}</p>}
      </div>
      {added && o.max_quantity > 1 && (
        <div className="rounded-xl bg-[var(--haip-card)] px-3 pb-3 text-[var(--haip-fg)] [&>div]:border-t-0"><Stepper o={o} q={q} onChange={onQty} /></div>
      )}
      <AddButton o={o} added={added} onToggle={onToggle} onDark />
      {o.needs_approval && <ConfirmNote dark />}
    </section>
  );
}

function Orders({ orders }: { orders: AddonOrder[] }) {
  if (!orders.length) return null;
  return (
    <section aria-label="Your add-ons so far" className="flex flex-col gap-3 rounded-2xl border border-[var(--haip-border)] bg-[var(--haip-card)] p-[18px]">
      <h2 className={cn(display, "text-[20px] font-semibold text-[var(--haip-nav-bg)]")}>Already on your stay</h2>
      {orders.map(o => (
        <div key={o.id} className="flex flex-col gap-2 border-t border-[var(--haip-band-bg)] pt-3 first-of-type:border-t-0 first-of-type:pt-0">
          <div className="flex items-start justify-between gap-3">
            <p className="text-[15px] font-semibold">{o.items.map(i => (i.quantity > 1 ? `${i.name} ×${i.quantity}` : i.name)).join(", ")}</p>
            <span className={cn("shrink-0 rounded-full px-2.5 py-1 text-[13px] font-semibold", ORDER_WORDS[o.status].tone)}>{ORDER_WORDS[o.status].label}</span>
          </div>
          {o.status === "declined" && o.decline_reason && <p className="text-[14px] text-[var(--haip-fg-muted)]">{o.decline_reason}</p>}
          {o.status === "awaiting_payment" && o.pay_url && (
            <a href={o.pay_url} className={cn("haip-btn-primary inline-flex min-h-12 items-center justify-center rounded-xl text-[16px] font-bold", s.press)}>
              Pay {inr(o.amount)}</a>
          )}
        </div>
      ))}
    </section>
  );
}

export default function GuestAddonsPage() {
  const { token } = useParams<{ token: string }>();
  const url = `${API}/public/addons/${encodeURIComponent(token)}`;
  const [view, setView] = useState<AddonsView | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "bad" | "offline">("loading");
  const [picks, setPicks] = useState<Picks>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const [today, setToday] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await fetch(url, { cache: "no-store" });
      if (!r.ok) { setState("bad"); return; }
      setView(await r.json());
      setState("ready");
    } catch { setState("offline"); }
  }, [url]);

  useEffect(() => { setToday(localToday()); load(); }, [load]);

  const offers = useMemo(() => view?.offers ?? [], [view]);
  const featured = offers.find(o => o.available) ?? null;
  const rest = offers.filter(o => o !== featured);
  const { lines, payNow, later } = useMemo(() => receipt(offers, picks), [offers, picks]);

  const toggle = (o: AddonOffer) => setPicks(p => {
    const n = { ...p };
    if (n[o.id] !== undefined) delete n[o.id]; else n[o.id] = o.default_quantity;
    return n;
  });
  const setQty = (o: AddonOffer, q: number) => setPicks(p => ({ ...p, [o.id]: Math.max(1, Math.min(o.max_quantity, q)) }));

  const pay = async () => {
    setBusy(true); setError(null);
    try {
      const r = await fetch(`${url}/orders`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ items: Object.entries(picks).map(([addon_id, quantity]) => ({ addon_id, quantity })) }),
      });
      const data = await r.json().catch(() => null);
      if (!r.ok) { setError(typeof data?.detail === "string" ? data.detail : "That didn't work. Please try again."); return; }
      if (data?.pay?.pay_url) { window.location.assign(data.pay.pay_url); return; }
      setPicks({}); setSent(true); await load();
    } catch { setError("No connection. Please try again."); }
    finally { setBusy(false); }
  };

  const days = view && today ? daysToGo(view.check_in, today) : null;
  const shell = "min-h-dvh bg-[var(--haip-app-bg)] px-4 pt-5 text-[var(--haip-fg)]";
  if (state === "loading") {
    return (
      <main className={shell} aria-busy="true">
        <div className="mx-auto flex max-w-lg flex-col gap-4">
          {["h-14", "h-[88px]", "h-[260px]", "h-[180px]"].map(h => <div key={h} className={cn("animate-pulse rounded-2xl bg-[var(--haip-band-bg)]", h)} />)}
        </div>
      </main>
    );
  }
  if (state !== "ready" || !view) {
    return (
      <main className={shell}>
        <div className="mx-auto flex max-w-lg flex-col gap-2 rounded-2xl border border-[var(--haip-border)] bg-[var(--haip-card)] p-6">
          <h1 className={cn(display, "text-[22px] font-semibold")}>{state === "offline" ? "No connection" : "This link does not work"}</h1>
          <p className="text-[15px] text-[var(--haip-fg-muted)]">
            {state === "offline" ? "Check your internet and open the link again." : "Please ask us for a new link on WhatsApp."}</p>
        </div>
      </main>
    );
  }
  return (
    <main className={cn(shell, "pb-32")}>
      <div className="mx-auto flex max-w-lg flex-col gap-5">
        <p className={cn(display, "text-[19px] font-bold text-[var(--haip-nav-bg)]")}>{view.business_name}</p>
        <div className="flex flex-col gap-1.5">
          <h1 className={cn(display, "text-[30px] font-semibold leading-[1.1] text-[var(--haip-nav-bg)]")}>
            {days === null ? `Hi ${view.guest_first_name}` : greeting(view.guest_first_name, days)}</h1>
          <p className="text-[15px] leading-snug text-[var(--haip-fg-muted)]">
            {view.open ? `A few extras for ${view.property_name}. Pay here, we sort the rest.` : "This booking can't take add-ons any more."}</p>
        </div>

        <section aria-label="Your stay" className="flex items-center gap-3 rounded-2xl border border-[var(--haip-border)] bg-[var(--haip-card)] px-4 py-3.5">
          <div className="flex size-10 flex-none items-center justify-center rounded-xl bg-[var(--haip-chip-bg)] text-[var(--haip-chip-fg)]">
            <CalendarIcon className="size-[22px]" /></div>
          <div className="min-w-0 flex-1">
            <p className="text-[16px] font-semibold">{view.property_name}</p>
            <p className="text-[14px] text-[var(--haip-fg-muted)]">{day(view.check_in)} to {day(view.check_out)} · {view.guests} {view.guests === 1 ? "guest" : "guests"}</p>
          </div>
          <span className="rounded-full bg-[var(--haip-chip-bg)] px-2.5 py-1 text-[13px] font-semibold text-[var(--haip-chip-fg)]">Confirmed</span>
        </section>

        {sent && (
          <p role="status" className="rounded-xl bg-[var(--haip-chip-bg)] px-3.5 py-3 text-[15px] text-[var(--haip-chip-fg)]">
            Request sent. We check and send you a payment link on WhatsApp.</p>
        )}
        <Orders orders={view.orders} />

        {view.open && offers.length === 0 && (
          <p className="rounded-2xl border border-[var(--haip-border)] bg-[var(--haip-card)] p-5 text-[15px] text-[var(--haip-fg-muted)]">
            Nothing to add for this stay right now. Message us on WhatsApp if you need anything.</p>
        )}
        {featured && <Featured o={featured} q={picks[featured.id]} onToggle={() => toggle(featured)} onQty={n => setQty(featured, n)} />}
        {rest.length > 0 && <h2 className={cn(display, "mt-1 text-[20px] font-semibold text-[var(--haip-nav-bg)]")}>More for your stay</h2>}
        {rest.map(o => <Pass key={o.id} o={o} q={picks[o.id]} onToggle={() => toggle(o)} onQty={n => setQty(o, n)} />)}

        {offers.length > 0 && (
          <section aria-label="Your add-ons" className="flex flex-col gap-3 rounded-2xl border border-[var(--haip-border)] bg-[var(--haip-card)] p-[18px]">
            <h2 className={cn(display, "text-[20px] font-semibold text-[var(--haip-nav-bg)]")}>Your add-ons</h2>
            {lines.length === 0 && <p className="text-[15px] text-[var(--haip-fg-muted)]">Nothing added yet. Tap Add on anything above.</p>}
            {lines.map(l => (
              <div key={l.id} className="flex items-baseline justify-between gap-3">
                <div className="min-w-0"><p className="text-[15px] font-semibold">{l.name}</p><p className="text-[13px] text-[var(--haip-fg-muted)]">{l.detail}</p></div>
                <p className={cn("whitespace-nowrap text-[15px] font-semibold tabular-nums", l.later && "text-[var(--haip-status-warning-fg)]")}>
                  {l.later ? `Later ${inr(l.amount)}` : inr(l.amount)}</p>
              </div>
            ))}
            <div className="h-px bg-[var(--haip-border)]" />
            <div className="flex items-baseline justify-between">
              <p className="text-[15px] font-semibold">Pay now</p>
              <p key={payNow} className={cn(display, s.total, "text-[24px] font-bold tabular-nums text-[var(--haip-nav-bg)]")} aria-live="polite">{inr(payNow)}</p>
            </div>
            {later > 0 && (
              <p className="rounded-lg bg-[var(--haip-status-warning-bg)] px-2.5 py-2 text-[13px] leading-snug text-[var(--haip-status-warning-fg)]">
                We check the items marked Later first, then send you a payment link on WhatsApp.</p>
            )}
          </section>
        )}
        <p className="flex items-start gap-2 px-1 text-[13px] leading-snug text-[var(--haip-fg-muted)]">
          <LockIcon className="mt-px size-4 flex-none" />Payment by Razorpay: UPI, cards or net banking. Prices as published by {view.business_name}.</p>
      </div>

      {view.open && offers.length > 0 && (
        <div className="fixed inset-x-0 bottom-0 bg-gradient-to-t from-[var(--haip-app-bg)] from-60% to-transparent px-4 pb-[max(16px,env(safe-area-inset-bottom))] pt-6">
          <div className="mx-auto flex max-w-lg flex-col gap-2">
            {error && <p role="alert" className="rounded-xl bg-[var(--haip-status-danger-bg)] px-3 py-2 text-[14px] text-[var(--haip-status-danger-fg)]">{error}</p>}
            <button type="button" disabled={busy || lines.length === 0} onClick={pay}
              className={cn("min-h-[54px] w-full rounded-xl text-[17px] font-bold", s.press,
                lines.length === 0 ? "bg-[var(--haip-border)] text-[var(--haip-fg-muted)]" : "haip-btn-primary")}>
              {busy ? "One moment…" : payLabel(payNow, later)}
            </button>
          </div>
        </div>
      )}
    </main>
  );
}
