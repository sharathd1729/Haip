// Multi-property sites (website phase 6): /stays/<slug> = one stay with its own photos, facts, FAQs and its own
// availability + booking (the same BookingForm, limited to this stay); /compare = every stay side by side (stacks on a
// phone, no sideways scrolling). Prices only where the business shows them (the API leaves them out otherwise).
import { BedDouble, Bath, Check, Users } from "lucide-react";
import { hrefOf, inr, type SiteEnv, type Stay } from "../types";
import { BookingForm } from "./booking-v2";
import type { LiveDataV2, StayItem } from "./types";

function photoSrc(ref: string | null | undefined, env: SiteEnv, w: number): string | null {
  if (!ref) return null;
  if (ref.startsWith("https://")) return ref;
  return ref.startsWith("asset:") && env.mode === "live" ? `/_haip/media/${ref.slice(6)}?w=${w}` : null;
}

export function StayPage({ stay, item, live, env }: { stay: Stay; item?: StayItem; live: LiveDataV2; env: SiteEnv }) {
  const site = live.site;
  const photos = [photoSrc(item?.photo, env, 1280), ...stay.photos].filter((p, i, a): p is string => !!p && a.indexOf(p) === i).slice(0, 7);
  const from = item?.from || (stay.from_price ? { amount: stay.from_price, label: "per night" } : null);
  const terms = { mode: site.booking_mode, rates: site.show_prices, holdMinutes: site.hold_minutes, depositPercent: site.deposit_percent };
  const paras = (stay.description || stay.summary || "").split(/\n\s*\n/).map(p => p.trim()).filter(Boolean);
  return (
    <>
      <section className="sv-sec sv-staypage">
        <div className="sv-wrap">
          <p className="sv-meta"><a href={hrefOf(env, "/compare")}>All stays</a></p>
          <h1 className="sv-h2">{stay.name}</h1>
          <p className="sv-stay__facts">
            {stay.sleeps > 0 && <span><Users aria-hidden="true" size={16} strokeWidth={1.75} />Sleeps {stay.sleeps}</span>}
            {!!stay.bedrooms && <span><BedDouble aria-hidden="true" size={16} strokeWidth={1.75} />{stay.bedrooms} bedroom{stay.bedrooms > 1 ? "s" : ""}</span>}
            {!!stay.bathrooms && <span><Bath aria-hidden="true" size={16} strokeWidth={1.75} />{stay.bathrooms} bathroom{stay.bathrooms > 1 ? "s" : ""}</span>}
          </p>
          {from && <p className="sv-meta">From <b>{inr(from.amount)}</b> {from.label}</p>}
          {photos.length > 0 && <div className="sv-staypage__photos">{photos.map((p, i) => (
            // eslint-disable-next-line @next/next/no-img-element
            <img key={p} src={p} alt={i === 0 ? stay.name : ""} loading={i === 0 ? "eager" : "lazy"} decoding="async" width={1280} height={853} />
          ))}</div>}
          <div className="sv-own">{paras.map((p, i) => <p key={i}>{p}</p>)}</div>
          {stay.amenities.length > 0 && <ul className="sv-ticks">{stay.amenities.map(a => <li key={a}><Check aria-hidden="true" size={18} />{a}</li>)}</ul>}
          {!!stay.extras?.length && <div><h2 className="sv-h3">Extras</h2><ul className="sv-ticks">{stay.extras.map(x => (
            <li key={x.id}><Check aria-hidden="true" size={18} />{x.name}{x.price ? ` · ${inr(x.price)}` : ""}</li>))}</ul></div>}
          {!!stay.faqs?.length && <div className="sv-faq--compact">{stay.faqs.map(f => (
            <details key={f.q}><summary>{f.q}</summary><p>{f.a}</p></details>))}</div>}
        </div>
      </section>
      {site.booking_mode !== "enquiry" && (
        <section className="sv-sec sv-band" id="book">
          <div className="sv-wrap"><h2 className="sv-h2">Check dates</h2>
            <BookingForm env={env} stays={[{ id: stay.id, name: stay.name, sleeps: stay.sleeps, from }]} today={site.today}
              cta="Send my dates" path={`/stays/${stay.slug}`} terms={terms} /></div>
        </section>
      )}
    </>
  );
}

export function ComparePage({ live, env }: { live: LiveDataV2; env: SiteEnv }) {
  const stays = live.stays_index || [];
  return (
    <section className="sv-sec sv-compare">
      <div className="sv-wrap">
        <header className="sv-head"><p className="sv-eyebrow">Stays</p><h1 className="sv-h2">Compare our stays</h1></header>
        {!stays.length ? <p className="sv-lede">Our stays are being added.</p> : (
          <div className="sv-compare__grid">{stays.map(s => {
            const src = photoSrc(s.photo, env, 640);
            return (
              <article key={s.id} className="sv-compare__col">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                {src && <img src={src} alt={s.name} loading="lazy" decoding="async" width={640} height={427} />}
                <h2 className="sv-h3">{s.name}</h2>
                <dl className="sv-compare__facts">
                  <div><dt>Sleeps</dt><dd>{s.sleeps || "—"}</dd></div>
                  <div><dt>Bedrooms</dt><dd>{s.bedrooms || "—"}</dd></div>
                  <div><dt>Bathrooms</dt><dd>{s.bathrooms || "—"}</dd></div>
                  {s.from && <div><dt>From</dt><dd>{inr(s.from.amount)} {s.from.label}</dd></div>}
                </dl>
                {s.amenities.length > 0 && <ul className="sv-ticks">{s.amenities.map(a => <li key={a}><Check aria-hidden="true" size={18} />{a}</li>)}</ul>}
                {s.slug && <a className="sv-btn" href={hrefOf(env, `/stays/${s.slug}#book`)}>Dates and booking</a>}
              </article>
            );
          })}</div>
        )}
      </div>
    </section>
  );
}
