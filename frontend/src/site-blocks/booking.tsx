"use client";
// The booking engine: dates (live availability) -> extras -> details -> pay (Razorpay link) or request -> confirmed.
// Every price shown comes from POST /quote; the browser never sends an amount. /book/done?hold=&s= is where
// Razorpay returns the guest: it polls the hold until the signed webhook has confirmed the booking.
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { readError } from "./util";
import { callApi, hrefOf, inr, str, type LiveData, type Props, type SiteEnv, type Stay } from "./types";

interface Quote {
  nights_count: number; nights?: { date: string; rate: string; gst_percent: string; gst: string }[];
  extras?: { id: string; name: string; quantity: number; amount: string }[];
  stay_net?: string; extras_net?: string; gst?: string; total?: string; pay_now?: string; balance?: string; balance_due?: string | null;
  gst_percent?: string | null; gst_registered?: boolean;
}

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const plus = (s: string, n: number) => { const d = new Date(s + "T00:00:00"); d.setDate(d.getDate() + n); return iso(d); };
const nice = (s: string) => new Date(s + "T00:00:00").toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" });

function Calendar({ month, taken, ci, co, today, onPick }: { month: string; taken: Set<string>; ci: string; co: string; today: string; onPick: (d: string) => void }) {
  const first = new Date(month + "-01T00:00:00");
  const lead = (first.getDay() + 6) % 7;
  const days = new Date(first.getFullYear(), first.getMonth() + 1, 0).getDate();
  return (
    <div className="k-cal" role="grid" aria-label={first.toLocaleDateString("en-IN", { month: "long", year: "numeric" })}>
      {["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"].map(d => <span key={d} className="dow">{d}</span>)}
      {Array.from({ length: lead }, (_, i) => <span key={`b${i}`} />)}
      {Array.from({ length: days }, (_, i) => {
        const d = `${month}-${String(i + 1).padStart(2, "0")}`;
        const off = d < today || taken.has(d);
        const cls = d === ci || d === co ? "edge" : ci && co && d > ci && d < co ? "in" : "";
        return <button key={d} type="button" className={cls} disabled={off && !(ci && !co && d > ci)} onClick={() => onPick(d)}
          aria-label={nice(d)} aria-pressed={!!cls}>{i + 1}</button>;
      })}
    </div>
  );
}

export function BookingEngine({ p, env, live }: { p: Props; env: SiteEnv; live: LiveData }) {
  const q = env.query || {};
  if (q.hold && q.s) return <Done env={env} holdId={q.hold} session={q.s} />;
  return <Flow p={p} env={env} live={live} />;
}

function Flow({ p, env, live }: { p: Props; env: SiteEnv; live: LiveData }) {
  const q = env.query || {};
  const today = live.site.today;
  const [stayId, setStayId] = useState(q.stay && live.stays.some(s => s.id === q.stay) ? q.stay : live.stays[0]?.id || "");
  const stay: Stay | undefined = live.stays.find(s => s.id === stayId);
  const [ci, setCi] = useState(q.checkin && q.checkin >= today ? q.checkin : "");
  const [co, setCo] = useState(q.checkout && q.checkout > (q.checkin || "") ? q.checkout : "");
  const [adults, setAdults] = useState(Number(q.adults) || 2);
  const [children, setChildren] = useState(0);
  const [month, setMonth] = useState((ci || today).slice(0, 7));
  const [taken, setTaken] = useState<Set<string>>(new Set());
  const [detail, setDetail] = useState<Stay | null>(null);
  const [extras, setExtras] = useState<Record<string, number>>({});
  const [quote, setQuote] = useState<{ q?: Quote; available?: boolean; error?: string; loading?: boolean }>({});
  const [step, setStep] = useState(1);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [requested, setRequested] = useState(false);
  const mode = live.site.booking_mode;
  const editor = !env.apiBase;

  useEffect(() => {
    if (editor || !stayId) return;
    callApi(env, `/availability?property_id=${stayId}&start=${month}-01&days=62`).then(r => (r.ok ? r.json() : { taken: [] }))
      .then(j => setTaken(new Set(j.taken || []))).catch(() => setTaken(new Set()));
  }, [stayId, month, editor, env]);
  useEffect(() => {
    if (editor || !stay) return;
    callApi(env, `/stays/${stay.slug}`).then(r => (r.ok ? r.json() : null)).then(setDetail).catch(() => setDetail(null));
  }, [stay, editor, env]);
  const extrasList = useMemo(() => Object.entries(extras).filter(([, n]) => n > 0).map(([id, quantity]) => ({ id, quantity })), [extras]);
  useEffect(() => {
    if (editor || !stayId || !ci || !co) return;
    let alive = true;
    setQuote({ loading: true });
    callApi(env, "/quote", { method: "POST", body: { property_id: stayId, check_in: ci, check_out: co, adults, children, extras: extrasList } })
      .then(async r => { if (!alive) return; if (!r.ok) return setQuote({ error: await readError(r, "Couldn't price these dates.") }); const j = await r.json(); setQuote({ q: j.quote, available: j.available }); })
      .catch(() => alive && setQuote({ error: "Couldn't reach us. Try again." }));
    return () => { alive = false; };
  }, [stayId, ci, co, adults, children, extrasList, editor, env]);

  const pick = (d: string) => {
    if (!ci || co || d <= ci) { setCi(d); setCo(""); return; }
    const span: string[] = [];
    for (let x = ci; x < d; x = plus(x, 1)) span.push(x);
    if (span.some(x => taken.has(x))) { setCi(d); setCo(""); return; }
    setCo(d);
  };
  const shiftMonth = (n: number) => { const d = new Date(month + "-01T00:00:00"); d.setMonth(d.getMonth() + n); setMonth(iso(d).slice(0, 7)); };
  const canNext = !!(ci && co && quote.available && !quote.error);
  const steps = ["Dates", "Extras", "Your details", mode === "request" ? "Send request" : "Payment"];

  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const name = str(f.get("name")).trim(), phone = str(f.get("phone")).trim();
    if (name.length < 2) return setErr("Enter your full name.");
    if (!/^[+\d\s-]{8,20}$/.test(phone)) return setErr("Enter a mobile number we can reach on WhatsApp.");
    if (!f.get("agree")) return setErr("Please accept the cancellation and house rules to continue.");
    if (editor) return;
    setBusy(true); setErr("");
    const utm = Object.fromEntries(Object.entries(q).filter(([k]) => k.startsWith("utm_")));
    const r = await callApi(env, "/holds", { method: "POST", body: {
      quote: { property_id: stayId, check_in: ci, check_out: co, adults, children, extras: extrasList },
      guest: { name, phone, email: f.get("email") || null, note: f.get("note") || null, arrival: f.get("arrival") || null,
        gstin: f.get("gstin") || null, company: f.get("company") || null, nationality: f.get("nationality") || null },
      consent: { transactional: true, marketing: f.get("offers") === "on" }, website: f.get("website") || null, utm } }).catch(() => null);
    setBusy(false);
    if (!r) return setErr("Couldn't reach us. Try again.");
    if (!r.ok) return setErr(await readError(r, "We couldn't hold these dates. Try again."));
    const j = await r.json();
    if (j.payment_url) window.location.href = j.payment_url;
    else setRequested(true);
  };

  if (!live.stays.length) return <div className="k-sec k-wrap"><p className="k-p">Booking opens once stays are added.</p></div>;
  if (requested) return (
    <div className="k-sec k-wrap"><div className="k-ok"><span className="k-kick">Request sent</span><h2 className="k-h2">We&apos;ll confirm on WhatsApp</h2>
      <p>The team checks the dates and sends you a payment link to confirm. Nothing has been charged.</p></div></div>
  );
  const Q = quote.q;
  return (
    <div className="k-sec k-wrap">
      <h1 className="k-h1" style={{ fontSize: 40 }}>{str(p.heading) || "Book your stay"}</h1>
      {str(p.intro) && <p className="k-p">{str(p.intro)}</p>}
      <div className="k-steps" aria-label="Steps">{steps.map((s, i) => <span key={s} className={i + 1 === step ? "on" : i + 1 < step ? "done" : ""}>{i + 1}. {s}</span>)}</div>
      <div className="k-layout">
        <div style={{ display: "grid", gap: 14 }}>
          {step === 1 && <>
            {live.stays.length > 1 && <label className="k-field"><span>Stay</span><select value={stayId} onChange={e => { setStayId(e.target.value); setExtras({}); }}>
              {live.stays.map(s => <option key={s.id} value={s.id}>{s.name}{s.sleeps ? ` · sleeps ${s.sleeps}` : ""}</option>)}</select></label>}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <button type="button" className="k-btn ghost" onClick={() => shiftMonth(-1)} disabled={month <= today.slice(0, 7)} aria-label="Previous month">‹</button>
              <b>{new Date(month + "-01T00:00:00").toLocaleDateString("en-IN", { month: "long", year: "numeric" })}</b>
              <button type="button" className="k-btn ghost" onClick={() => shiftMonth(1)} aria-label="Next month">›</button>
            </div>
            <Calendar month={month} taken={taken} ci={ci} co={co} today={today} onPick={pick} />
            <p className="k-small">{ci && co ? `${nice(ci)} to ${nice(co)}` : ci ? "Now pick your check-out day." : "Pick your check-in day. Crossed-out days are booked."}</p>
            <div className="k-grid2" style={{ gap: 10 }}>
              <label className="k-field"><span>Adults</span><select value={adults} onChange={e => setAdults(Number(e.target.value))}>{Array.from({ length: Math.max(1, stay?.max_adults || 6) }, (_, i) => i + 1).map(n => <option key={n}>{n}</option>)}</select></label>
              <label className="k-field"><span>Children</span><select value={children} onChange={e => setChildren(Number(e.target.value))}>{[0, 1, 2, 3, 4].map(n => <option key={n}>{n}</option>)}</select></label>
            </div>
            {quote.error && <p className="k-err" role="alert">{quote.error}</p>}
            {quote.available === false && <p className="k-err" role="alert">Some of these nights were just booked. Pick other dates.</p>}
            <button type="button" className="k-btn" disabled={!canNext} onClick={() => setStep((detail?.extras || []).length ? 2 : 3)}>Continue</button>
          </>}
          {step === 2 && <>
            <h2 className="k-h2" style={{ fontSize: 28 }}>Make it yours</h2>
            {(detail?.extras || []).map(x => (
              <label key={x.id} className="k-opt">
                <input type="checkbox" checked={(extras[x.id] || 0) > 0} onChange={e => setExtras(s => ({ ...s, [x.id]: e.target.checked ? 1 : 0 }))} />
                <span><b>{x.name}</b>{x.description && <><br /><span className="k-small">{x.description}</span></>}</span>
                <b>{x.price ? inr(x.price) : ""}</b>
              </label>
            ))}
            <div style={{ display: "flex", gap: 8 }}><button type="button" className="k-btn ghost" onClick={() => setStep(1)}>Back</button><button type="button" className="k-btn" onClick={() => setStep(3)}>Continue</button></div>
          </>}
          {step >= 3 && (
            <form className="k-form" onSubmit={submit} noValidate>
              <h2 className="k-h2" style={{ fontSize: 28 }}>Your details</h2>
              <label className="k-field"><span>Full name</span><input name="name" autoComplete="name" required /></label>
              <div className="k-grid2" style={{ gap: 10 }}>
                <label className="k-field"><span>Mobile (WhatsApp)</span><input name="phone" inputMode="tel" autoComplete="tel" placeholder="+91 98765 43210" required /></label>
                <label className="k-field"><span>Email</span><input name="email" type="email" autoComplete="email" /></label>
              </div>
              <div className="k-grid2" style={{ gap: 10 }}>
                <label className="k-field"><span>Arrival time</span><select name="arrival"><option value="">Not sure yet</option><option>Before noon</option><option>12 pm to 5 pm</option><option>5 pm to 9 pm</option><option>After 9 pm</option></select></label>
                <label className="k-field"><span>Nationality</span><input name="nationality" defaultValue="Indian" /></label>
              </div>
              <label className="k-field"><span>Anything we should know? (optional)</span><textarea name="note" rows={2} /></label>
              <details className="k-faq"><summary>Need a GST invoice for your company?</summary>
                <div className="k-grid2" style={{ gap: 10, paddingBottom: 12 }}><label className="k-field"><span>GSTIN</span><input name="gstin" maxLength={15} /></label><label className="k-field"><span>Company</span><input name="company" /></label></div></details>
              <input name="website" tabIndex={-1} autoComplete="off" aria-hidden="true" style={{ position: "absolute", left: "-9999px" }} />
              <label className="k-check"><input type="checkbox" name="agree" /> <span>I accept the <a className="k-link" href={hrefOf(env, "/policies")} target="_blank" rel="noopener noreferrer">cancellation policy and house rules</a>, and agree to booking updates on WhatsApp and email.</span></label>
              <label className="k-check"><input type="checkbox" name="offers" /> <span>Send me occasional offers (optional).</span></label>
              {err && <p className="k-err" role="alert">{err}</p>}
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <button type="button" className="k-btn ghost" onClick={() => setStep(1)}>Back</button>
                <button type="submit" className="k-btn" disabled={busy || editor}>
                  {busy ? "Holding your dates…" : mode === "request" ? "Send booking request" : Q?.pay_now ? `Pay ${inr(Q.pay_now)} securely` : "Continue"}
                </button>
              </div>
              <p className="k-small">{mode === "request" ? "No payment now. The team confirms and sends a payment link." : `Your dates are held for ${live.site.hold_minutes} minutes while you pay by UPI, card or netbanking through Razorpay.`}</p>
            </form>
          )}
        </div>
        <aside className="k-sum" aria-label="Summary">
          <b>{stay?.name}</b>
          <p className="k-small">{ci && co ? `${nice(ci)} to ${nice(co)} · ${adults} adult${adults > 1 ? "s" : ""}${children ? `, ${children} children` : ""}` : "Pick your dates"}</p>
          {quote.loading && <p className="k-small">Pricing…</p>}
          {Q && Q.total && (
            <table className="k-table"><tbody>
              <tr><td>{Q.nights_count} night{Q.nights_count > 1 ? "s" : ""}</td><td className="r">{inr(Q.stay_net)}</td></tr>
              {(Q.extras || []).map(x => <tr key={x.id}><td>{x.name}</td><td className="r">{inr(x.amount)}</td></tr>)}
              {Number(Q.gst) > 0 && <tr><td>GST{Q.gst_percent ? ` (${Number(Q.gst_percent)}%)` : " (5% and 18% by night)"}</td><td className="r">{inr(Q.gst)}</td></tr>}
              <tr><td><b>Total</b></td><td className="r"><b>{inr(Q.total)}</b></td></tr>
              {mode === "deposit" && Q.pay_now && <tr><td>Pay now ({live.site.deposit_percent}%)</td><td className="r">{inr(Q.pay_now)}</td></tr>}
              {Q.balance && Number(Q.balance) > 0 && mode !== "request" && <tr><td className="k-small">Balance due {Q.balance_due ? nice(Q.balance_due) : "before arrival"}</td><td className="r k-small">{inr(Q.balance)}</td></tr>}
            </tbody></table>
          )}
          {!live.site.show_prices && <p className="k-small">We share the price for your dates before you pay.</p>}
        </aside>
      </div>
    </div>
  );
}

function Done({ env, holdId, session }: { env: SiteEnv; holdId: string; session: string }) {
  const [st, setSt] = useState<{ status?: string; booking_ref?: string; manage_token?: string; error?: string }>({});
  useEffect(() => {
    if (!env.apiBase) return;
    let tries = 0, stop = false;
    const tick = async () => {
      if (stop) return;
      const r = await callApi(env, `/holds/${holdId}?s=${encodeURIComponent(session)}`).catch(() => null);
      if (r && r.ok) {
        const j = await r.json();
        setSt(j);
        if (j.status === "confirmed" || j.status === "paid_conflict" || j.status === "expired") return;
      } else if (r && r.status === 404) return setSt({ error: "We couldn't find this booking." });
      if (++tries < 30) setTimeout(tick, 2000);
      else setSt(s => ({ ...s, error: "Your payment is being confirmed. You'll get a WhatsApp and email shortly." }));
    };
    tick();
    return () => { stop = true; };
  }, [env, holdId, session]);
  return (
    <div className="k-sec k-wrap" style={{ maxWidth: 720 }}>
      {st.status === "confirmed" ? (
        <div className="k-ok"><span className="k-kick">Booking confirmed</span><h1 className="k-h2">See you soon</h1>
          <p>Booking reference <b>{st.booking_ref}</b>. A confirmation is on its way by email and WhatsApp.</p>
          {st.manage_token && <p style={{ marginTop: 10 }}><a className="k-btn" href={hrefOf(env, `/my-booking?t=${st.manage_token}`)}>View my booking</a></p>}</div>
      ) : st.status === "paid_conflict" ? (
        <div className="k-ok"><h1 className="k-h2">We received your payment</h1><p>Those dates were taken a moment before you paid. The team will call you to move your stay or refund you in full.</p></div>
      ) : st.error ? <p className="k-p">{st.error}</p> : (
        <div className="k-ok" role="status"><h1 className="k-h2">Confirming your payment…</h1><p>This takes a few seconds. Please keep this page open.</p></div>
      )}
    </div>
  );
}
