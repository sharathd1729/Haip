// v2 sections, part 3: the business's own stays (caravans, villas, rooms) from HAIP Properties. Returns null when there
// are none, like every other section.
import { BedDouble, Check, Users } from "lucide-react";
import { BookingForm, type BookStay } from "./booking-v2";
import { hrefOf, inr } from "../types";
import { bound, Head, Img, Section, WaButton, type Ctx } from "./parts";
import { txt, type SectionV2, type StayItem } from "./types";

/** "Check dates": hidden when the owner chose "Guests just message you" (booking mode enquiry) or there's nothing to book.
 * Variant "with-rates" shows each day's nightly rate, only when the business shows prices (grounded). */
export function Booking(s: SectionV2, ctx: Ctx) {
  const stays = (bound(ctx, s).items || []) as BookStay[];
  const site = ctx.live.site;
  if (!stays.length || site.booking_mode === "enquiry") return null;
  const terms = { mode: site.booking_mode, rates: s.variant === "with-rates" && site.show_prices, holdMinutes: site.hold_minutes,
    depositPercent: site.deposit_percent };
  return (
    <Section s={s} band>
      <div className="sv-wrap">
        <Head ctx={ctx} s={s} />
        <BookingForm env={ctx.env} stays={stays} today={ctx.live.site.today} cta={txt(s.slots.cta_label) || "Send my dates"}
          path={ctx.page.slug} terms={terms} />
      </div>
    </Section>
  );
}

/** An approved library photo ("asset:<id>") or the property's own https photo. */
function StayPhoto({ item, ctx, eager }: { item: StayItem; ctx: Ctx; eager?: boolean }) {
  if (!item.photo) return <div className="sv-stay__ph" aria-hidden="true" />;
  if (item.photo.startsWith("https://")) {
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={item.photo} alt={item.name} loading={eager ? "eager" : "lazy"} decoding="async" />;
  }
  return <Img ref_={item.photo} ctx={ctx} eager={eager} sizes="(min-width: 760px) 33vw, 100vw" />;
}

function Facts({ item }: { item: StayItem }) {
  return (
    <p className="sv-stay__facts">
      {item.sleeps > 0 && <span><Users aria-hidden="true" size={16} strokeWidth={1.75} />Sleeps {item.sleeps}</span>}
      {!!item.bedrooms && <span><BedDouble aria-hidden="true" size={16} strokeWidth={1.75} />{item.bedrooms} bedroom{item.bedrooms > 1 ? "s" : ""}</span>}
    </p>
  );
}

function Body({ item, ctx, s }: { item: StayItem; ctx: Ctx; s: SectionV2 }) {
  return (
    <div className="sv-stay__body">
      <h3 className="sv-h3">{item.name}</h3>
      <Facts item={item} />
      {item.from && <p className="sv-meta">From <b>{inr(item.from.amount)}</b> {item.from.label}</p>}
      {item.summary && <p className="sv-muted">{item.summary}</p>}
      {item.amenities.length > 0 && <ul className="sv-ticks">{item.amenities.slice(0, 4).map(a => <li key={a}><Check aria-hidden="true" size={18} />{a}</li>)}</ul>}
      <div className="sv-actions">
        {item.slug && <a className="sv-btn sv-btn--sm" href={hrefOf(ctx.env, `/stays/${item.slug}`)}>See {item.name}</a>}
        <WaButton wa={bound(ctx, s).wa} label={`Ask about ${item.name}`} quiet />
      </div>
    </div>
  );
}

export function Stays(s: SectionV2, ctx: Ctx) {
  const items = (bound(ctx, s).items || []) as StayItem[];
  if (!items.length) return null;
  if (s.variant === "rows") {
    return (
      <Section s={s}>
        <div className="sv-wrap">
          <Head ctx={ctx} s={s} />
          <div className="sv-stay-rows">
            {items.map((item, i) => (
              <article key={item.id} className="sv-stay sv-stay--row sv-rise">
                <div className="sv-stay__media"><StayPhoto item={item} ctx={ctx} eager={i === 0} /></div>
                <Body item={item} ctx={ctx} s={s} />
              </article>
            ))}
          </div>
        </div>
      </Section>
    );
  }
  if (s.variant === "feature" && items.length > 1) {
    const [top, ...rest] = items;
    return (
      <Section s={s} band>
        <div className="sv-wrap">
          <Head ctx={ctx} s={s} />
          <article className="sv-stay sv-stay--row sv-stay--big sv-rise">
            <div className="sv-stay__media"><StayPhoto item={top} ctx={ctx} eager /></div>
            <Body item={top} ctx={ctx} s={s} />
          </article>
          <div className="sv-cards sv-stay-grid">{rest.map(item => (
            <article key={item.id} className="sv-stay sv-rise"><div className="sv-stay__media"><StayPhoto item={item} ctx={ctx} /></div><Body item={item} ctx={ctx} s={s} /></article>
          ))}</div>
        </div>
      </Section>
    );
  }
  return (
    <Section s={s}>
      <div className="sv-wrap">
        <Head ctx={ctx} s={s} />
        {items.length > 1 && <p className="sv-meta"><a href={hrefOf(ctx.env, "/compare")}>Compare all {items.length} stays</a></p>}
        <div className="sv-cards sv-stay-grid">
          {items.map(item => (
            <article key={item.id} className="sv-stay sv-rise">
              <div className="sv-stay__media"><StayPhoto item={item} ctx={ctx} /></div>
              <Body item={item} ctx={ctx} s={s} />
            </article>
          ))}
        </div>
      </div>
    </Section>
  );
}

/** "Your own text": the owner's own words (house rules, their story, how to reach them), with an optional photo. */
/** "Seasonal offer": a band with the owner's words and, while its promo code is usable, the code to type at checkout.
 * The amount ("15% off") comes from HAIP and shows only when the business shows prices. */
export function OfferSection(s: SectionV2, ctx: Ctx) {
  const promo = bound(ctx, s).promo;
  const until = promo?.until ? new Date(promo.until + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short" }) : null;
  const line = promo ? [promo.label, `use code ${promo.code}`, promo.min_nights > 1 ? `stays of ${promo.min_nights}+ nights` : "",
    until ? `until ${until}` : ""].filter(Boolean).join(" · ") : "";
  const card = s.variant === "card";
  const label = txt(s.slots.cta_label) || "Check dates";
  const book = ctx.live.doc.pages.flatMap(p => p.sections.filter(x => x.type === "booking").map(x => ({ slug: p.slug, id: x.id })))[0];
  return (
    <Section s={s} className={card ? undefined : "sv-inverse"}>
      <div className={`sv-wrap sv-rise ${card ? "sv-offer-card" : "sv-banner"}`}>
        <div>
          <Head ctx={ctx} s={s} />
          {txt(s.slots.text) && <p className="sv-lede">{txt(s.slots.text)}</p>}
          {line && <p className="sv-offer__code">{line.charAt(0).toUpperCase() + line.slice(1)}</p>}
        </div>
        <div className="sv-actions">{book ? <a className="sv-btn" href={hrefOf(ctx.env, `${book.slug}#${book.id}`)}>{label}</a>
          : <WaButton wa={bound(ctx, s).wa} label={label} />}</div>
      </div>
    </Section>
  );
}

export function TextSection(s: SectionV2, ctx: Ctx) {
  const body = txt(s.slots.body).split(/\n\s*\n/).map(p => p.trim()).filter(Boolean);
  if (!txt(s.slots.heading) && !body.length) return null;
  const words = (
    <div className="sv-rise">
      <Head ctx={ctx} s={s} />
      <div className="sv-own">{body.map((p, i) => <p key={i}>{p}</p>)}</div>
    </div>
  );
  const photo = s.variant === "with-photo" && s.slots.media ? <div className="sv-own__photo"><Img ref_={s.slots.media} ctx={ctx} sizes="(min-width: 860px) 50vw, 100vw" /></div> : null;
  return (
    <Section s={s}>
      {photo ? <div className="sv-wrap sv-split sv-own__split">{words}{photo}</div> : <div className="sv-wrap sv-narrow">{words}</div>}
    </Section>
  );
}
