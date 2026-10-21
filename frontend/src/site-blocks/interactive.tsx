"use client";
// Interactive site pieces: booking bar, price box, gallery lightbox, contact form, My booking. They talk to the
// guest API only through callApi(env) (the sites app proxies /_haip/api/* to HAIP with the hostname); in the editor
// (env.mode === "editor") they render but never send anything.
import { useEffect, useState, type FormEvent } from "react";
import { callApi, hrefOf, inr, str, type LiveData, type Props, type SiteEnv, type Stay } from "./types";
import { readError } from "./util";

export { BookingEngine } from "./booking";

const addDays = (iso: string, n: number) => {
  const d = new Date(iso + "T00:00:00");
  d.setDate(d.getDate() + n);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};


export function BookingBar({ p, env, live }: { p: Props; env: SiteEnv; live: LiveData }) {
  const today = live.site.today;
  const [stay, setStay] = useState("");
  const [ci, setCi] = useState(addDays(today, 14));
  const [co, setCo] = useState(addDays(today, 16));
  const [adults, setAdults] = useState("2");
  const go = (e: FormEvent) => {
    e.preventDefault();
    if (env.mode === "editor") return;
    const q = new URLSearchParams({ checkin: ci, checkout: co, adults, ...(stay ? { stay } : {}) });
    window.location.href = hrefOf(env, `/book?${q}`);
  };
  return (
    <div className="k-sec k-wrap" style={{ paddingBlock: 8 }}>
      <form className="k-bbar" onSubmit={go}>
        <label>Stay<select value={stay} onChange={e => setStay(e.target.value)}><option value="">Any</option>{live.stays.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
        <label>Check-in<input type="date" value={ci} min={today} onChange={e => { setCi(e.target.value); if (e.target.value >= co) setCo(addDays(e.target.value, 1)); }} /></label>
        <label>Check-out<input type="date" value={co} min={addDays(ci, 1)} onChange={e => setCo(e.target.value)} /></label>
        <label>Guests<select value={adults} onChange={e => setAdults(e.target.value)}>{[1, 2, 3, 4, 5, 6, 8, 10].map(n => <option key={n}>{n}</option>)}</select></label>
        <button className="k-btn" type="submit">{str(p.cta_label) || "Check availability"}</button>
      </form>
    </div>
  );
}

export function PriceBox({ env, live, stay }: { env: SiteEnv; live: LiveData; stay: Stay }) {
  const today = live.site.today;
  const [ci, setCi] = useState(addDays(today, 14));
  const [co, setCo] = useState(addDays(today, 16));
  const [adults, setAdults] = useState(Math.min(2, stay.max_adults || 2));
  const [state, setState] = useState<{ loading: boolean; error?: string; total?: string; available?: boolean }>({ loading: false });
  useEffect(() => {
    if (!env.apiBase || co <= ci) return;
    let alive = true;
    setState({ loading: true });
    callApi(env, "/quote", { method: "POST", body: { property_id: stay.id, check_in: ci, check_out: co, adults, children: 0, extras: [] } })
      .then(async r => {
        if (!alive) return;
        if (!r.ok) return setState({ loading: false, error: await readError(r, "Couldn't price these dates.") });
        const j = await r.json();
        setState({ loading: false, available: j.available, total: j.quote?.total });
      })
      .catch(() => alive && setState({ loading: false, error: "Couldn't reach us. Try again." }));
    return () => { alive = false; };
  }, [ci, co, adults, stay.id, env]);
  const enquiry = live.site.booking_mode === "enquiry";
  const book = () => {
    const q = new URLSearchParams({ stay: stay.id, checkin: ci, checkout: co, adults: String(adults) });
    window.location.href = hrefOf(env, enquiry ? `/contact?${q}` : `/book?${q}`);
  };
  return (
    <aside className="k-sum" aria-label={`Book ${stay.name}`}>
      {live.site.show_prices && stay.from_price && <p className="k-price" style={{ fontSize: 22 }}>From {inr(stay.from_price)} <small>/ night</small></p>}
      <div className="k-grid2" style={{ gap: 8 }}>
        <label className="k-field"><span>Check-in</span><input type="date" value={ci} min={today} onChange={e => { setCi(e.target.value); if (e.target.value >= co) setCo(addDays(e.target.value, 1)); }} /></label>
        <label className="k-field"><span>Check-out</span><input type="date" value={co} min={addDays(ci, 1)} onChange={e => setCo(e.target.value)} /></label>
      </div>
      <label className="k-field"><span>Guests</span><select value={adults} onChange={e => setAdults(Number(e.target.value))}>
        {Array.from({ length: Math.max(1, stay.sleeps || stay.max_adults || 2) }, (_, i) => i + 1).map(n => <option key={n}>{n}</option>)}</select></label>
      {state.loading ? <p className="k-small">Checking…</p> : state.error ? <p className="k-err" role="alert">{state.error}</p>
        : state.available === false ? <p className="k-err" role="alert">Booked on some of these nights. Try other dates.</p>
        : state.total ? <p className="k-price">{inr(state.total)} <small>total incl. GST</small></p> : null}
      <button type="button" className="k-btn" style={{ justifySelf: "stretch" }} disabled={state.available === false} onClick={book}>
        {enquiry ? "Ask about these dates" : live.site.booking_mode === "request" ? "Request to book" : "Reserve"}
      </button>
      <p className="k-small">{enquiry || live.site.booking_mode === "request" ? "No payment now. We confirm on WhatsApp." : "You won't be charged yet."}</p>
    </aside>
  );
}

export function GalleryGrid({ images, mosaic }: { images: { src: string; alt: string }[]; mosaic?: boolean }) {
  const [open, setOpen] = useState<number | null>(null);
  useEffect(() => {
    if (open === null) return;
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(null); if (e.key === "ArrowRight") setOpen(i => (i === null ? i : (i + 1) % images.length)); if (e.key === "ArrowLeft") setOpen(i => (i === null ? i : (i + images.length - 1) % images.length)); };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [open, images.length]);
  return (
    <>
      <div className={`k-gal ${mosaic ? "mosaic" : ""}`}>
        {images.map((im, i) => (
          // eslint-disable-next-line @next/next/no-img-element
          <button key={i} type="button" onClick={() => setOpen(i)} aria-label={`Open photo ${i + 1}`}><img className="k-img" src={im.src} alt={im.alt} loading="lazy" /></button>
        ))}
      </div>
      {open !== null && (
        <div className="k-lightbox" role="dialog" aria-label="Photo" onClick={e => { if (e.target === e.currentTarget) setOpen(null); }}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={images[open].src} alt={images[open].alt} />
          <button type="button" className="k-btn alt" style={{ position: "absolute", top: 14, right: 14 }} onClick={() => setOpen(null)} autoFocus>Close</button>
        </div>
      )}
    </>
  );
}

export function ContactForm({ env, stays }: { env: SiteEnv; stays: Stay[] }) {
  const pre = env.query || {};
  const [sent, setSent] = useState(false);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    if (!f.get("agree")) return setErr("Tick the box so we can reply to you.");
    if (!env.apiBase) return setSent(true);
    setBusy(true);
    setErr("");
    const utm = Object.fromEntries(Object.entries(pre).filter(([k]) => k.startsWith("utm_")));
    const r = await callApi(env, "/enquiries", { method: "POST", body: {
      name: f.get("name"), phone: f.get("phone"), email: f.get("email") || null, message: f.get("message") || null,
      property_id: f.get("stay") || null, check_in: pre.checkin || null, check_out: pre.checkout || null,
      adults: pre.adults ? Number(pre.adults) : null, website: f.get("website") || null, utm, path: "/contact",
      consent: { transactional: true, marketing: f.get("offers") === "on" } } }).catch(() => null);
    setBusy(false);
    if (r && r.ok) setSent(true);
    else setErr(r ? await readError(r, "Couldn't send. Try WhatsApp instead.") : "Couldn't reach us. Try WhatsApp instead.");
  };
  if (sent) return <div className="k-ok"><b>Thanks, we&apos;ve got it.</b><p>We usually reply on WhatsApp within the hour.</p></div>;
  return (
    <form className="k-sum k-form" onSubmit={submit} noValidate>
      <b>Send an enquiry</b>
      <label className="k-field"><span>Name</span><input name="name" required autoComplete="name" /></label>
      <label className="k-field"><span>Mobile (WhatsApp)</span><input name="phone" required inputMode="tel" autoComplete="tel" placeholder="+91 98765 43210" /></label>
      <label className="k-field"><span>Email (optional)</span><input name="email" type="email" autoComplete="email" /></label>
      {stays.length > 1 && <label className="k-field"><span>Stay</span><select name="stay" defaultValue={pre.stay || ""}><option value="">Not sure yet</option>{stays.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>}
      <label className="k-field"><span>Message</span><textarea name="message" rows={3} defaultValue={pre.checkin ? `Dates: ${pre.checkin} to ${pre.checkout}${pre.adults ? `, ${pre.adults} guests` : ""}` : ""} /></label>
      <input name="website" tabIndex={-1} autoComplete="off" aria-hidden="true" style={{ position: "absolute", left: "-9999px" }} />
      <label className="k-check"><input type="checkbox" name="agree" /> <span>Contact me about this enquiry on WhatsApp, phone or email.</span></label>
      <label className="k-check"><input type="checkbox" name="offers" /> <span>Send me occasional offers (optional).</span></label>
      {err && <p className="k-err" role="alert">{err}</p>}
      <button className="k-btn" type="submit" disabled={busy}>{busy ? "Sending…" : "Send"}</button>
    </form>
  );
}

interface Manage { booking_ref: string; status: string; property: string; check_in: string; check_out: string; adults: number; children: number;
  total: string; paid: string; outstanding: string; schedule: { label: string; amount: string; due_date: string; status: string }[] }

export function ManageBooking({ p, env }: { p: Props; env: SiteEnv }) {
  const token = env.query?.t || "";
  const [data, setData] = useState<Manage | null>(null);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  useEffect(() => {
    if (!token || !env.apiBase) return;
    callApi(env, `/manage?t=${encodeURIComponent(token)}`).then(async r => (r.ok ? setData(await r.json()) : setErr(await readError(r, "This link has expired."))))
      .catch(() => setErr("Couldn't reach us. Try again."));
  }, [token, env]);
  const lookup = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!env.apiBase) return;
    const f = new FormData(e.currentTarget);
    const r = await callApi(env, "/manage/lookup", { method: "POST", body: { ref: f.get("ref"), phone: f.get("phone") } }).catch(() => null);
    setMsg(r && r.ok ? (await r.json()).message : "Couldn't reach us. Try again.");
  };
  const pay = async () => {
    if (!env.apiBase) return;
    const r = await callApi(env, `/manage/pay?t=${encodeURIComponent(token)}`, { method: "POST" });
    if (r.ok) window.location.href = (await r.json()).payment_url;
    else setErr(await readError(r, "Online payment isn't available. Contact us."));
  };
  return (
    <div className="k-sec k-wrap" style={{ maxWidth: 720 }}>
      <h1 className="k-h1" style={{ fontSize: 40 }}>{str(p.heading) || "My booking"}</h1>
      {data ? (
        <div className="k-sum">
          <span className="k-kick">{data.booking_ref} · {data.status}</span>
          <h2 className="k-h2" style={{ fontSize: 28 }}>{data.property}</h2>
          <p>{data.check_in} to {data.check_out} · {data.adults} adult{data.adults > 1 ? "s" : ""}{data.children ? `, ${data.children} children` : ""}</p>
          <table className="k-table"><tbody>
            <tr><td>Total</td><td className="r">{inr(data.total)}</td></tr><tr><td>Paid</td><td className="r">{inr(data.paid)}</td></tr>
            <tr><td><b>Still to pay</b></td><td className="r"><b>{inr(data.outstanding)}</b></td></tr>
            {data.schedule.map((s, i) => <tr key={i}><td className="k-small">{s.label}, due {s.due_date}</td><td className="r k-small">{inr(s.amount)} · {s.status}</td></tr>)}
          </tbody></table>
          {Number(data.outstanding) > 0 && <button className="k-btn" type="button" onClick={pay}>Pay {inr(data.outstanding)}</button>}
          {err && <p className="k-err" role="alert">{err}</p>}
          <p className="k-small">To change dates or cancel, message us on WhatsApp with your booking reference.</p>
        </div>
      ) : (
        <form className="k-sum k-form" onSubmit={lookup} noValidate>
          {err && <p className="k-err" role="alert">{err}</p>}
          <p className="k-p">Enter your booking reference and the mobile you booked with. We&apos;ll send you a link.</p>
          <label className="k-field"><span>Booking reference</span><input name="ref" required placeholder="#1A2B3C4D" /></label>
          <label className="k-field"><span>Mobile</span><input name="phone" required inputMode="tel" autoComplete="tel" /></label>
          <button className="k-btn" type="submit">Send me a link</button>
          {msg && <p className="k-ok" role="status">{msg}</p>}
        </form>
      )}
    </div>
  );
}
