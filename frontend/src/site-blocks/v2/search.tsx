"use client";
// Website W5: "Find your stay" (/stays on a v2 site). Dates, guests, place, sort and amenity filters over the site's
// stays; with dates it asks the guest API which stays are free (the same /availability the booking form uses) and lists
// free ones first, a taken one saying so instead of hiding. Prices only where the business shows them (item.from).
import { useMemo, useState } from "react";
import { BedDouble, Users } from "lucide-react";
import { callApi, hrefOf, inr, type SiteEnv } from "../types";
import type { LiveDataV2, StayItem } from "./types";

type Sort = "price" | "bedrooms" | "guests" | "name";

function photo(ref: string | null, env: SiteEnv): string | null {
  if (!ref) return null;
  if (ref.startsWith("https://")) return ref;
  return ref.startsWith("asset:") ? (env.mode === "live" ? `/_haip/media/${ref.slice(6)}?w=640` : env.assets[ref.slice(6)]?.src || null) : null;
}

const nightsBetween = (a: string, b: string) => Math.round((Date.parse(b) - Date.parse(a)) / 86400000);

export function StaySearch({ live, env }: { live: LiveDataV2; env: SiteEnv }) {
  const stays = live.stays_index || [];
  const today = live.site.today;
  const [ci, setCi] = useState(env.query?.check_in || "");
  const [co, setCo] = useState(env.query?.check_out || "");
  const [guests, setGuests] = useState(Number(env.query?.guests) || 2);
  const [place, setPlace] = useState("");
  const [sort, setSort] = useState<Sort>(stays.some(s => s.from) ? "price" : "name");
  const [wanted, setWanted] = useState<string[]>([]);
  const [free, setFree] = useState<Record<string, boolean> | null>(null);
  const [state, setState] = useState<"idle" | "busy" | "offline" | "error">("idle");
  const places = [...new Set(stays.map(s => s.city).filter((c): c is string => !!c))].sort();
  const amenities = useMemo(() => {
    const count = new Map<string, number>();
    stays.forEach(s => s.amenities.forEach(a => count.set(a, (count.get(a) || 0) + 1)));
    return [...count.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6).map(([a]) => a);
  }, [stays]);
  const nights = ci && co ? nightsBetween(ci, co) : 0;

  async function search() {
    if (!ci || nights < 1) { setFree(null); return; }
    setState("busy");
    try {
      const out: Record<string, boolean> = {};
      await Promise.all(stays.map(async s => {
        const r = await callApi(env, `/availability?property_id=${encodeURIComponent(s.id)}&start=${ci}&days=${Math.min(nights, 120)}`);
        if (!r.ok) throw new Error(String(r.status));
        const taken: string[] = (await r.json()).taken || [];
        out[s.id] = !taken.some(d => d >= ci && d < co);
      }));
      setFree(out); setState("idle");
    } catch (e) {
      setState(e instanceof Error && e.message === "offline" ? "offline" : "error");
    }
  }

  const shown = stays
    .filter(s => !place || s.city === place)
    .filter(s => !s.sleeps || s.sleeps >= guests)
    .filter(s => wanted.every(a => s.amenities.includes(a)))
    .sort((a, b) => (sort === "price" ? Number(a.from?.amount ?? Infinity) - Number(b.from?.amount ?? Infinity)
      : sort === "bedrooms" ? (b.bedrooms || 0) - (a.bedrooms || 0) : sort === "guests" ? b.sleeps - a.sleeps : a.name.localeCompare(b.name)))
    .sort((a, b) => (free ? Number(!!free[b.id]) - Number(!!free[a.id]) : 0));
  const q = ci && co ? `?check_in=${ci}&check_out=${co}&guests=${guests}` : "";

  return (
    <section className="sv-sec sv-search">
      <div className="sv-wrap">
        <header className="sv-head"><h1 className="sv-h2">Find your stay</h1>
          <p className="sv-lede">{free ? `${Object.values(free).filter(Boolean).length} of ${stays.length} free for your dates` : `${stays.length} stays at ${live.doc.site.name}`}</p></header>
        <form className="sv-search__bar" onSubmit={e => { e.preventDefault(); search(); }}>
          {places.length > 1 && <label>Where<select value={place} onChange={e => setPlace(e.target.value)}><option value="">Any place</option>{places.map(p => <option key={p}>{p}</option>)}</select></label>}
          <label>Check-in<input type="date" min={today} value={ci} onChange={e => { setCi(e.target.value); setFree(null); }} /></label>
          <label>Check-out<input type="date" min={ci || today} value={co} onChange={e => { setCo(e.target.value); setFree(null); }} /></label>
          <label>Guests<input type="number" min={1} max={40} value={guests} onChange={e => setGuests(Math.max(1, Number(e.target.value) || 1))} /></label>
          <button className="sv-btn" type="submit" disabled={state === "busy"}>{state === "busy" ? "Checking…" : "Search"}</button>
        </form>
        {state === "offline" && <p className="sv-meta" role="status">Free dates show on the live site.</p>}
        {state === "error" && <p className="sv-meta" role="alert">Couldn&apos;t check the dates just now. Try again.</p>}
        <div className="sv-search__tools">
          {amenities.length > 0 && <div className="sv-chips" role="group" aria-label="Must have">{amenities.map(a => (
            <button key={a} type="button" aria-pressed={wanted.includes(a)} onClick={() => setWanted(w => (w.includes(a) ? w.filter(x => x !== a) : [...w, a]))}>{a}</button>))}</div>}
          <label className="sv-search__sort">Sort<select value={sort} onChange={e => setSort(e.target.value as Sort)}>
            {stays.some(s => s.from) && <option value="price">Price</option>}<option value="bedrooms">Bedrooms</option><option value="guests">Guests</option><option value="name">Name</option></select></label>
        </div>
        {!shown.length ? <p className="sv-meta">No stay fits all of that. Try fewer guests or fewer must-haves.</p> : (
          <ul className="sv-search__list">{shown.map(s => <Row key={s.id} s={s} env={env} free={free ? !!free[s.id] : null} href={hrefOf(env, `/stays/${s.slug}${q}`)} />)}</ul>
        )}
      </div>
    </section>
  );
}

function Row({ s, env, free, href }: { s: StayItem; env: SiteEnv; free: boolean | null; href: string }) {
  const img = photo(s.photo, env);
  return (
    <li className={`sv-search__row${free === false ? " sv-search__row--taken" : ""}`}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      {img ? <img src={img} alt="" loading="lazy" decoding="async" width={640} height={427} /> : <span className="sv-search__noimg" />}
      <div className="sv-search__body">
        {s.city && <p className="sv-eyebrow">{s.city}</p>}
        <a className="sv-search__name" href={href}>{s.name}</a>
        <p className="sv-stay__facts">{s.sleeps > 0 && <span><Users aria-hidden="true" size={16} strokeWidth={1.75} />Sleeps {s.sleeps}</span>}
          {!!s.bedrooms && <span><BedDouble aria-hidden="true" size={16} strokeWidth={1.75} />{s.bedrooms} bedroom{s.bedrooms > 1 ? "s" : ""}</span>}</p>
        {s.summary && <p className="sv-search__sum">{s.summary}</p>}
      </div>
      <div className="sv-search__side">
        {free !== null && <p className={free ? "sv-search__free" : "sv-search__taken"}>{free ? "Free for your dates" : "Taken on these dates"}</p>}
        {s.from && <p className="sv-meta">From <b>{inr(s.from.amount)}</b> {s.from.label}</p>}
        <a className="sv-btn sv-btn--sm" href={href}>{free === false ? "See other dates" : "View"}</a>
      </div>
    </li>
  );
}
