// Website W4: the parts of a stay page design (/stays/<slug>) and a package page design (/packages/<key>). Everything
// shown comes from that one stay (env.stay, the public stay detail) or package (live.packages_index); the owner writes
// only the small heading above each part. Server-rendered (BookingForm is the only interactive piece).
import { Bath, BedDouble, Check, MapPin, Users } from "lucide-react";
import { hrefOf, inr, type SiteEnv, type Stay } from "../types";
import { BookingForm } from "./booking-v2";
import { type Ctx, Head, Section, WaButton } from "./parts";
import type { LiveDataV2, SectionV2, StayItem } from "./types";

function src(ref: string | null | undefined, env: SiteEnv, w: number): string | null {
  if (!ref) return null;
  if (ref.startsWith("https://")) return ref;
  if (!ref.startsWith("asset:")) return null;
  return env.mode === "live" ? `/_haip/media/${ref.slice(6)}?w=${w}` : env.assets[ref.slice(6)]?.src || null;
}

const itemOf = (live: LiveDataV2, stay: Stay): StayItem | undefined => (live.stays_index || []).find(i => i.id === stay.id);

export function stayPhotos(stay: Stay, live: LiveDataV2, env: SiteEnv): string[] {
  return [src(itemOf(live, stay)?.photo, env, 1280), ...stay.photos.map(p => src(p, env, 1280))]
    .filter((p, i, a): p is string => !!p && a.indexOf(p) === i).slice(0, 24);
}

/* eslint-disable @next/next/no-img-element */
export function StayGallery(s: SectionV2, ctx: Ctx) {
  const stay = ctx.env.stay;
  if (!stay) return null;
  const photos = stayPhotos(stay, ctx.live, ctx.env);
  if (!photos.length) return null;
  const img = (p: string, i: number) => <img key={p} src={p} alt={i === 0 ? stay.name : ""} loading={i === 0 && ctx.first ? "eager" : "lazy"} decoding="async" width={1280} height={853} />;
  return (
    <Section s={s}>
      <div className="sv-wrap">
        <Head ctx={{ ...ctx, first: false }} s={s} />
        <div className={`sv-tgal sv-tgal--${s.variant}`}>{photos.slice(0, s.variant === "strip" ? 8 : 5).map(img)}</div>
        {photos.length > 5 && (
          <details className="sv-tgal__all"><summary className="sv-btn sv-btn--quiet">View all {photos.length} photos</summary>
            <div className="sv-tgal__grid">{photos.map(img)}</div></details>
        )}
      </div>
    </Section>
  );
}

export function StayDetails(s: SectionV2, ctx: Ctx) {
  const stay = ctx.env.stay;
  if (!stay) return null;
  const item = itemOf(ctx.live, stay);
  const from = item?.from || (stay.from_price ? { amount: stay.from_price, label: "per night" } : null);
  const paras = (stay.description || stay.summary || "").split(/\n\s*\n/).map(p => p.trim()).filter(Boolean);
  const shown = stay.amenities.slice(0, 8), more = stay.amenities.slice(8);
  return (
    <Section s={s}>
      <div className={`sv-wrap sv-tdetails sv-tdetails--${s.variant}`}>
        <div className="sv-tdetails__main">
          {stay.city && <p className="sv-eyebrow">{stay.city}</p>}
          <h1 className="sv-h2">{stay.name}</h1>
          <p className="sv-stay__facts">
            {stay.sleeps > 0 && <span><Users aria-hidden="true" size={16} strokeWidth={1.75} />Sleeps {stay.sleeps}</span>}
            {!!stay.bedrooms && <span><BedDouble aria-hidden="true" size={16} strokeWidth={1.75} />{stay.bedrooms} bedroom{stay.bedrooms > 1 ? "s" : ""}</span>}
            {!!stay.bathrooms && <span><Bath aria-hidden="true" size={16} strokeWidth={1.75} />{stay.bathrooms} bathroom{stay.bathrooms > 1 ? "s" : ""}</span>}
          </p>
          {from && <p className="sv-meta">From <b>{inr(from.amount)}</b> {from.label}</p>}
          <div className="sv-own">{paras.map((p, i) => <p key={i}>{p}</p>)}</div>
        </div>
        {stay.amenities.length > 0 && (
          <div className="sv-tdetails__side">
            <h2 className="sv-h3">{String(s.slots.heading || "") || "What's there"}</h2>
            <ul className="sv-ticks">{shown.map(a => <li key={a}><Check aria-hidden="true" size={18} />{a}</li>)}</ul>
            {more.length > 0 && <details><summary className="sv-link">View all {stay.amenities.length} amenities</summary>
              <ul className="sv-ticks">{more.map(a => <li key={a}><Check aria-hidden="true" size={18} />{a}</li>)}</ul></details>}
          </div>
        )}
      </div>
    </Section>
  );
}

export function StayRules(s: SectionV2, ctx: Ctx) {
  const r = ctx.live.policies?.stay_rules;
  const rules = [
    ...(r?.check_in_time ? [`Check-in from ${r.check_in_time}`] : []), ...(r?.check_out_time ? [`Check-out by ${r.check_out_time}`] : []),
    ...(r?.min_age ? [`Lead guest ${r.min_age}+`] : []), ...(r?.id_required ? ["ID needed at check-in"] : []), ...(r?.house_rules || []),
  ];
  if (!rules.length) return null;
  return (
    <Section s={s}>
      <div className="sv-wrap">
        <Head ctx={{ ...ctx, first: false }} s={{ ...s, slots: { ...s.slots, heading: s.slots.heading || "House rules" } }} />
        {s.variant === "list" ? <ul className="sv-ticks">{rules.map(x => <li key={x}><Check aria-hidden="true" size={18} />{x}</li>)}</ul>
          : <ul className="sv-chips">{rules.map(x => <li key={x}>{x}</li>)}</ul>}
        <p className="sv-meta"><a href={hrefOf(ctx.env, "/policies")}>Cancellation and payment terms</a></p>
      </div>
    </Section>
  );
}

export function StayMap(s: SectionV2, ctx: Ctx) {
  const stay = ctx.env.stay;
  if (!stay || !(stay.lat && stay.lng) && !stay.city) return null;
  const q = stay.lat && stay.lng ? `${stay.lat},${stay.lng}` : stay.city;
  return (
    <Section s={s}>
      <div className="sv-wrap">
        <Head ctx={{ ...ctx, first: false }} s={{ ...s, slots: { ...s.slots, heading: s.slots.heading || "Where it is" } }} />
        <div className="sv-map">
          <MapPin aria-hidden="true" size={28} className="sv-map__pin" />
          <p>{stay.city || stay.name}</p>
          <a className="sv-btn sv-btn--quiet" href={`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(q)}`} target="_blank" rel="noopener noreferrer">Get directions</a>
        </div>
        {!stay.address && <p className="sv-meta">The exact address comes with your booking.</p>}
      </div>
    </Section>
  );
}

export function StayBooking(s: SectionV2, ctx: Ctx) {
  const stay = ctx.env.stay, site = ctx.live.site;
  if (!stay) return null;
  const from = itemOf(ctx.live, stay)?.from || (stay.from_price ? { amount: stay.from_price, label: "per night" } : null);
  const terms = { mode: site.booking_mode, rates: site.show_prices, holdMinutes: site.hold_minutes, depositPercent: site.deposit_percent };
  const wa = ctx.live.page_wa[ctx.page.slug] || ctx.live.page_wa["/"] || null;
  return (
    <Section s={s} band>
      <div className="sv-wrap" id="book">
        <Head ctx={{ ...ctx, first: false }} s={{ ...s, slots: { ...s.slots, heading: s.slots.heading || "Check dates" } }} />
        {site.booking_mode !== "enquiry" && (
          <BookingForm env={ctx.env} stays={[{ id: stay.id, name: stay.name, sleeps: stay.sleeps, from }]} today={site.today}
            cta="Check availability" path={`/stays/${stay.slug}`} terms={terms} />
        )}
        <div className="sv-tbook__ask"><WaButton wa={wa} label="Ask on WhatsApp" quiet /></div>
      </div>
    </Section>
  );
}

export function PackageDetails(s: SectionV2, ctx: Ctx) {
  const p = (ctx.live.packages_index || []).find(x => x.key === ctx.env.packageKey);
  if (!p) return null;
  return (
    <Section s={s}>
      <div className={`sv-wrap sv-tdetails sv-tdetails--${s.variant}`}>
        <div className="sv-tdetails__main">
          {s.slots.eyebrow ? <p className="sv-eyebrow">{String(s.slots.eyebrow)}</p> : p.destinations.length > 0 && <p className="sv-eyebrow">{p.destinations.join(" · ")}</p>}
          <h1 className="sv-h2">{p.name}</h1>
          <p className="sv-stay__facts">{p.length && <span>{p.length}</span>}{p.max_guests > 0 && <span><Users aria-hidden="true" size={16} strokeWidth={1.75} />Up to {p.max_guests}</span>}</p>
          {p.summary && <div className="sv-own"><p>{p.summary}</p></div>}
          {p.days.length > 0 && <><h2 className="sv-h3">{String(s.slots.heading || "") || "Day by day"}</h2>
            <ol className="sv-tdays">{p.days.map((d, i) => <li key={i}><b>Day {i + 1}</b> {d}</li>)}</ol></>}
        </div>
        <div className="sv-tdetails__side">
          {p.inclusions.length > 0 && <><h2 className="sv-h3">What&apos;s included</h2>
            <ul className="sv-ticks">{p.inclusions.map(x => <li key={x}><Check aria-hidden="true" size={18} />{x}</li>)}</ul></>}
          <p className="sv-meta">{p.price ? <>From <b>{inr(p.price.amount)}</b> {p.price.label}</> : p.price_label}</p>
          <WaButton wa={p.wa} label="Ask about this trip" />
        </div>
      </div>
    </Section>
  );
}
