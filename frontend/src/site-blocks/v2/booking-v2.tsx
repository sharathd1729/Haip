"use client";
// "Check dates" on a v2 site: pick a stay, see its free nights (GET /availability, from the HAIP calendar: bookings, blocks,
// synced calendars, other guests' live holds), pick dates, then:
//   instant / deposit  POST /quote (the server prices the stay; the browser never sends an amount) and POST /holds, which holds
//                      the dates and returns a Razorpay link. Razorpay sends the guest back to /book/done (sites app), which
//                      waits for the signed webhook to confirm the booking.
//   request / enquiry  POST /enquiries: a lead with the dates; the team confirms and quotes on WhatsApp. A handoff-price site
//                      always lands here (the server turns a paying mode into "request", website_spec_service.guest_terms).
// `rates` (variant "with-rates", grounded price mode only): each free day shows its nightly rate from GET /availability.
// In a preview or the editor (no apiBase) the form shows but sends nothing.
import { useEffect, useState, type FormEvent } from "react";
import { callApi, hrefOf, inr, type SiteEnv } from "../types";
import { adIds, readError, track } from "../util";
import type { FromPrice } from "./types";

export interface BookStay { id: string; name: string; sleeps: number; from?: FromPrice | null }
export interface BookTerms { mode: "instant" | "deposit" | "request" | "enquiry"; rates: boolean; holdMinutes: number; depositPercent: number }
interface Quote { nights_count: number; total?: string; gst?: string; pay_now?: string; balance?: string; balance_due?: string | null }

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const plus = (s: string, n: number) => { const d = new Date(s + "T00:00:00"); d.setDate(d.getDate() + n); return iso(d); };
const nice = (s: string) => new Date(s + "T00:00:00").toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" });
const phoneOk = (p: string) => /^[+\d\s-]{8,20}$/.test(p);

export function BookingForm({ env, stays, today, cta, path, terms }: { env: SiteEnv; stays: BookStay[]; today: string; cta: string; path: string; terms: BookTerms }) {
  const [stayId, setStayId] = useState(stays[0]?.id || "");
  const [month, setMonth] = useState(today.slice(0, 7));
  const [taken, setTaken] = useState<Set<string>>(new Set());
  const [rates, setRates] = useState<Record<string, string>>({});
  const [ci, setCi] = useState("");
  const [co, setCo] = useState("");
  const [adults, setAdults] = useState(2);
  const [quote, setQuote] = useState<{ q?: Quote; available?: boolean; error?: string; loading?: boolean }>({});
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const live = !!env.apiBase;
  const pay = terms.mode === "instant" || terms.mode === "deposit";
  const stay = stays.find(s => s.id === stayId);

  useEffect(() => {
    if (!live || !stayId) return;
    let alive = true;
    callApi(env, `/availability?property_id=${encodeURIComponent(stayId)}&start=${month}-01&days=62`)
      .then(r => (r.ok ? r.json() : { taken: [] }))
      .then(j => { if (alive) { setTaken(new Set(j.taken || [])); setRates(j.rates || {}); } })
      .catch(() => { if (alive) { setTaken(new Set()); setRates({}); } });
    return () => { alive = false; };
  }, [stayId, month, live, env]);

  useEffect(() => {
    if (!pay || !live || !stayId || !ci || !co) return;
    let alive = true;
    setQuote({ loading: true });
    callApi(env, "/quote", { method: "POST", body: { property_id: stayId, check_in: ci, check_out: co, adults, children: 0, extras: [] } })
      .then(async r => {
        if (!alive) return;
        if (!r.ok) return setQuote({ error: await readError(r, "We couldn't price these dates.") });
        const j = await r.json();
        setQuote({ q: j.quote, available: j.available });
      })
      .catch(() => alive && setQuote({ error: "Couldn't reach us. Try again." }));
    return () => { alive = false; };
  }, [pay, stayId, ci, co, adults, live, env]);

  const pick = (d: string) => {
    if (!ci || co || d <= ci) { setCi(d); setCo(""); setQuote({}); return; }
    for (let x = ci; x < d; x = plus(x, 1)) if (taken.has(x)) { setCi(d); setCo(""); setQuote({}); return; }
    setCo(d);
  };
  const shift = (n: number) => { const d = new Date(month + "-01T00:00:00"); d.setMonth(d.getMonth() + n); const m = iso(d).slice(0, 7); if (m >= today.slice(0, 7)) setMonth(m); };

  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const name = String(f.get("name") || "").trim(), phone = String(f.get("phone") || "").trim();
    if (!ci || !co) return setErr("Pick your check-in and check-out dates first.");
    if (name.length < 2) return setErr("Enter your name.");
    if (!phoneOk(phone)) return setErr("Enter a mobile number we can reach on WhatsApp.");
    if (pay && !f.get("agree")) return setErr("Please accept the cancellation policy and house rules to continue.");
    if (pay && (quote.available === false || quote.error || !quote.q)) return setErr(quote.error || "Pick dates that are free first.");
    if (!live) return setErr("This is a preview: nothing is sent from here.");
    setBusy(true); setErr("");
    if (pay) {
      const utm = Object.fromEntries(Object.entries(env.query || {}).filter(([k]) => k.startsWith("utm_")));
      const r = await callApi(env, "/holds", { method: "POST", body: {
        quote: { property_id: stayId, check_in: ci, check_out: co, adults, children: 0, extras: [] },
        guest: { name, phone, email: String(f.get("email") || "").trim() || null, note: String(f.get("note") || "").trim() || null },
        consent: { transactional: true, marketing: f.get("offers") === "on" }, website: f.get("website") || null, utm, path, ...adIds() } }).catch(() => null);
      if (!r) { setBusy(false); return setErr("Couldn't reach us. Try again."); }
      if (!r.ok) { setBusy(false); return setErr(await readError(r, "We couldn't hold these dates. Try again.")); }
      const j = await r.json();
      track(j.payment_url ? "InitiateCheckout" : "Lead", j.event_id, j.payment_url ? { value: Number(j.quote?.total) || undefined, currency: "INR" } : undefined);
      if (j.payment_url) { window.location.href = j.payment_url; return; }
      setBusy(false);
      return setSent(true);
    }
    const r = await callApi(env, "/enquiries", { method: "POST", body: {
      name, phone, property_id: stayId || null, check_in: ci, check_out: co, adults,
      message: [`Booking request for ${stay?.name || "a stay"}`, String(f.get("note") || "").trim()].filter(Boolean).join(". "),
      website: f.get("website") || null, path, ...adIds() } }).catch(() => null);
    setBusy(false);
    if (!r) return setErr("Couldn't reach us. Try again, or message us on WhatsApp.");
    if (!r.ok) return setErr(await readError(r, "We couldn't send that. Try again, or message us on WhatsApp."));
    track("Lead", (await r.json().catch(() => ({})))?.event_id);
    setSent(true);
  };

  if (sent) return (
    <div className="sv-book__done" role="status">
      <p className="sv-h3">Thank you! Your dates are with us.</p>
      <p className="sv-muted">{nice(ci)} to {nice(co)}, {adults} guest{adults > 1 ? "s" : ""}. We&apos;ll confirm on WhatsApp shortly.</p>
    </div>
  );

  const first = new Date(month + "-01T00:00:00");
  const lead = (first.getDay() + 6) % 7;
  const days = new Date(first.getFullYear(), first.getMonth() + 1, 0).getDate();
  const showRates = terms.rates && Object.keys(rates).length > 0;
  const Q = quote.q;
  return (
    <form className="sv-book" onSubmit={submit} noValidate>
      {stays.length > 1 && (
        <div className="sv-book__stays" role="radiogroup" aria-label="Which stay?">
          {stays.map(s => (
            <button key={s.id} type="button" role="radio" aria-checked={s.id === stayId} className={`sv-chip${s.id === stayId ? " is-on" : ""}`}
              onClick={() => { setStayId(s.id); setCi(""); setCo(""); setQuote({}); }}>{s.name}{s.sleeps ? ` · sleeps ${s.sleeps}` : ""}</button>
          ))}
        </div>
      )}
      <div className="sv-book__cal">
        {stay?.from && <p className="sv-meta">From <b>{inr(stay.from.amount)}</b> {stay.from.label}</p>}
        <div className="sv-book__month">
          <button type="button" className="sv-chip" aria-label="Previous month" onClick={() => shift(-1)} disabled={month <= today.slice(0, 7)}>‹</button>
          <span className="sv-h3">{first.toLocaleDateString("en-IN", { month: "long", year: "numeric" })}</span>
          <button type="button" className="sv-chip" aria-label="Next month" onClick={() => shift(1)}>›</button>
        </div>
        <div className={`sv-cal${showRates ? " sv-cal--rates" : ""}`} role="grid">
          {["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"].map(d => <span key={d} className="sv-cal__dow">{d}</span>)}
          {Array.from({ length: lead }, (_, i) => <span key={`b${i}`} />)}
          {Array.from({ length: days }, (_, i) => {
            const d = `${month}-${String(i + 1).padStart(2, "0")}`;
            const isTaken = taken.has(d), past = d < today;
            const rate = showRates && !isTaken && !past ? rates[d] : undefined;
            const cls = d === ci || d === co ? " is-edge" : ci && co && d > ci && d < co ? " is-in" : isTaken ? " is-taken" : "";
            return (
              <button key={d} type="button" className={`sv-cal__day${cls}`} disabled={past || (isTaken && !(ci && !co && d > ci))}
                onClick={() => pick(d)} aria-pressed={!!cls.trim() && !isTaken}
                aria-label={`${nice(d)}${isTaken ? ", sold out" : rate ? `, ${inr(rate)} a night` : ""}`}>
                {i + 1}{rate && <small className="sv-cal__rate" aria-hidden="true">{inr(rate).slice(1)}</small>}
              </button>
            );
          })}
        </div>
        <p className="sv-meta">{ci && co ? `${nice(ci)} to ${nice(co)}` : ci ? "Now pick your check-out date" : "Tap your check-in date. Crossed-out days are sold out."}
          {showRates && " Nightly rates in ₹; your total is worked out for your exact dates."}</p>
      </div>
      <div className="sv-book__form">
        <label className="sv-field"><span>Guests</span>
          <span className="sv-stepper">
            <button type="button" className="sv-chip" aria-label="Fewer guests" onClick={() => setAdults(a => Math.max(1, a - 1))}>−</button>
            <b aria-live="polite">{adults}</b>
            <button type="button" className="sv-chip" aria-label="More guests" onClick={() => setAdults(a => Math.min(30, a + 1))}>+</button>
          </span></label>
        {pay && ci && co && (
          <div className="sv-book__sum" aria-live="polite">
            {quote.loading && <p className="sv-meta">Working out your price…</p>}
            {quote.error && <p className="sv-err" role="alert">{quote.error}</p>}
            {quote.available === false && <p className="sv-err" role="alert">Some of these nights were just booked. Pick other dates.</p>}
            {Q?.total && quote.available && (
              <dl className="sv-sum">
                <div><dt>{Q.nights_count} night{Q.nights_count > 1 ? "s" : ""}{Number(Q.gst) > 0 ? ", incl. GST" : ""}</dt><dd>{inr(Q.total)}</dd></div>
                {terms.mode === "deposit" && Q.pay_now && <div><dt>Pay now ({terms.depositPercent}%)</dt><dd>{inr(Q.pay_now)}</dd></div>}
                {Number(Q.balance) > 0 && <div className="sv-muted"><dt>Balance due {Q.balance_due ? nice(Q.balance_due) : "before arrival"}</dt><dd>{inr(Q.balance)}</dd></div>}
              </dl>
            )}
          </div>
        )}
        <label className="sv-field"><span>Your name</span><input name="name" autoComplete="name" required /></label>
        <label className="sv-field"><span>WhatsApp number</span><input name="phone" type="tel" inputMode="tel" autoComplete="tel" required /></label>
        {pay && <label className="sv-field"><span>Email (for your receipt, optional)</span><input name="email" type="email" autoComplete="email" /></label>}
        <label className="sv-field"><span>Anything we should know? (optional)</span><input name="note" maxLength={300} /></label>
        <input name="website" className="sv-hp" tabIndex={-1} autoComplete="off" aria-hidden="true" />
        {pay && <>
          <label className="sv-check"><input type="checkbox" name="agree" /> <span>I accept the <a href={hrefOf(env, "/policies")} target="_blank" rel="noopener noreferrer">cancellation policy and house rules</a>, and agree to booking updates on WhatsApp and email.</span></label>
          <label className="sv-check"><input type="checkbox" name="offers" /> <span>Send me occasional offers (optional).</span></label>
        </>}
        {err && <p className="sv-err" role="alert">{err}</p>}
        <button type="submit" className="sv-btn sv-btn--block" disabled={busy}>
          {busy ? (pay ? "Holding your dates…" : "Sending…") : pay ? (Q?.pay_now && quote.available ? `Pay ${inr(Q.pay_now)} securely` : "Book and pay") : cta}
        </button>
        <p className="sv-meta">{pay
          ? `Pay by UPI, card or netbanking on Razorpay's secure page. Your dates are held for ${terms.holdMinutes} minutes while you pay.`
          : "No payment now. We confirm your dates and the price on WhatsApp."}</p>
      </div>
    </form>
  );
}
