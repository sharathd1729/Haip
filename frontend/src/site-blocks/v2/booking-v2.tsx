"use client";
// "Check dates" on a v2 site: pick a stay, see its free nights (GET /availability, from the HAIP calendar: bookings, blocks,
// synced calendars), pick dates and send them with a name and phone (POST /enquiries). The request lands in HAIP as a lead
// with the dates; the team confirms and quotes on WhatsApp. No price is shown or sent from here. In a preview or the editor
// (no apiBase) the form shows but sends nothing.
import { useEffect, useState, type FormEvent } from "react";
import { callApi, type SiteEnv } from "../types";
import { readError } from "../util";

export interface BookStay { id: string; name: string; sleeps: number }

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const plus = (s: string, n: number) => { const d = new Date(s + "T00:00:00"); d.setDate(d.getDate() + n); return iso(d); };
const nice = (s: string) => new Date(s + "T00:00:00").toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" });

export function BookingForm({ env, stays, today, cta, path }: { env: SiteEnv; stays: BookStay[]; today: string; cta: string; path: string }) {
  const [stayId, setStayId] = useState(stays[0]?.id || "");
  const [month, setMonth] = useState(today.slice(0, 7));
  const [taken, setTaken] = useState<Set<string>>(new Set());
  const [ci, setCi] = useState("");
  const [co, setCo] = useState("");
  const [adults, setAdults] = useState(2);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const live = !!env.apiBase;

  useEffect(() => {
    if (!live || !stayId) return;
    let alive = true;
    callApi(env, `/availability?property_id=${encodeURIComponent(stayId)}&start=${month}-01&days=62`)
      .then(r => (r.ok ? r.json() : { taken: [] })).then(j => alive && setTaken(new Set(j.taken || []))).catch(() => alive && setTaken(new Set()));
    return () => { alive = false; };
  }, [stayId, month, live, env]);

  const pick = (d: string) => {
    if (!ci || co || d <= ci) { setCi(d); setCo(""); return; }
    for (let x = ci; x < d; x = plus(x, 1)) if (taken.has(x)) { setCi(d); setCo(""); return; }
    setCo(d);
  };
  const shift = (n: number) => { const d = new Date(month + "-01T00:00:00"); d.setMonth(d.getMonth() + n); const m = iso(d).slice(0, 7); if (m >= today.slice(0, 7)) setMonth(m); };

  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const name = String(f.get("name") || "").trim(), phone = String(f.get("phone") || "").trim();
    if (!ci || !co) return setErr("Pick your check-in and check-out dates first.");
    if (name.length < 2) return setErr("Enter your name.");
    if (!/^[+\d\s-]{8,20}$/.test(phone)) return setErr("Enter a mobile number we can reach on WhatsApp.");
    if (!live) return setErr("This is a preview: nothing is sent from here.");
    setBusy(true); setErr("");
    const stay = stays.find(s => s.id === stayId);
    const r = await callApi(env, "/enquiries", { method: "POST", body: {
      name, phone, property_id: stayId || null, check_in: ci, check_out: co, adults,
      message: [`Booking request for ${stay?.name || "a stay"}`, String(f.get("note") || "").trim()].filter(Boolean).join(". "),
      website: f.get("website") || null, path } }).catch(() => null);
    setBusy(false);
    if (!r) return setErr("Couldn't reach us. Try again, or message us on WhatsApp.");
    if (!r.ok) return setErr(await readError(r, "We couldn't send that. Try again, or message us on WhatsApp."));
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
  return (
    <form className="sv-book" onSubmit={submit} noValidate>
      {stays.length > 1 && (
        <div className="sv-book__stays" role="radiogroup" aria-label="Which stay?">
          {stays.map(s => (
            <button key={s.id} type="button" role="radio" aria-checked={s.id === stayId} className={`sv-chip${s.id === stayId ? " is-on" : ""}`}
              onClick={() => { setStayId(s.id); setCi(""); setCo(""); }}>{s.name}{s.sleeps ? ` · sleeps ${s.sleeps}` : ""}</button>
          ))}
        </div>
      )}
      <div className="sv-book__cal">
        <div className="sv-book__month">
          <button type="button" className="sv-chip" aria-label="Previous month" onClick={() => shift(-1)} disabled={month <= today.slice(0, 7)}>‹</button>
          <span className="sv-h3">{first.toLocaleDateString("en-IN", { month: "long", year: "numeric" })}</span>
          <button type="button" className="sv-chip" aria-label="Next month" onClick={() => shift(1)}>›</button>
        </div>
        <div className="sv-cal" role="grid">
          {["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"].map(d => <span key={d} className="sv-cal__dow">{d}</span>)}
          {Array.from({ length: lead }, (_, i) => <span key={`b${i}`} />)}
          {Array.from({ length: days }, (_, i) => {
            const d = `${month}-${String(i + 1).padStart(2, "0")}`;
            const isTaken = taken.has(d), past = d < today;
            const cls = d === ci || d === co ? " is-edge" : ci && co && d > ci && d < co ? " is-in" : isTaken ? " is-taken" : "";
            return <button key={d} type="button" className={`sv-cal__day${cls}`} disabled={past || (isTaken && !(ci && !co && d > ci))}
              onClick={() => pick(d)} aria-pressed={!!cls.trim() && !isTaken} aria-label={`${nice(d)}${isTaken ? ", booked" : ""}`}>{i + 1}</button>;
          })}
        </div>
        <p className="sv-meta">{ci && co ? `${nice(ci)} to ${nice(co)}` : ci ? "Now pick your check-out date" : "Tap your check-in date. Crossed-out days are booked."}</p>
      </div>
      <div className="sv-book__form">
        <label className="sv-field"><span>Guests</span>
          <span className="sv-stepper">
            <button type="button" className="sv-chip" aria-label="Fewer guests" onClick={() => setAdults(a => Math.max(1, a - 1))}>−</button>
            <b aria-live="polite">{adults}</b>
            <button type="button" className="sv-chip" aria-label="More guests" onClick={() => setAdults(a => Math.min(30, a + 1))}>+</button>
          </span></label>
        <label className="sv-field"><span>Your name</span><input name="name" autoComplete="name" required /></label>
        <label className="sv-field"><span>WhatsApp number</span><input name="phone" type="tel" inputMode="tel" autoComplete="tel" required /></label>
        <label className="sv-field"><span>Anything we should know? (optional)</span><input name="note" maxLength={300} /></label>
        <input name="website" className="sv-hp" tabIndex={-1} autoComplete="off" aria-hidden="true" />
        {err && <p className="sv-err" role="alert">{err}</p>}
        <button type="submit" className="sv-btn sv-btn--block" disabled={busy}>{busy ? "Sending…" : cta}</button>
        <p className="sv-meta">No payment now. We confirm your dates and the price on WhatsApp.</p>
      </div>
    </form>
  );
}
