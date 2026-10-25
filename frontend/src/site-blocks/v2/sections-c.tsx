// v2 sections, part 3: the business's own stays (caravans, villas, rooms) from HAIP Properties. Returns null when there
// are none, like every other section.
import { BedDouble, Check, Users } from "lucide-react";
import { BookingForm, type BookStay } from "./booking-v2";
import { bound, Head, Img, Section, WaButton, type Ctx } from "./parts";
import { txt, type SectionV2, type StayItem } from "./types";

/** "Check dates": hidden when the owner chose "Guests just message you" (booking mode enquiry) or there's nothing to book. */
export function Booking(s: SectionV2, ctx: Ctx) {
  const stays = (bound(ctx, s).items || []) as BookStay[];
  if (!stays.length || ctx.live.site.booking_mode === "enquiry") return null;
  return (
    <Section s={s} band>
      <div className="sv-wrap">
        <Head ctx={ctx} s={s} />
        <BookingForm env={ctx.env} stays={stays} today={ctx.live.site.today} cta={txt(s.slots.cta_label) || "Send my dates"} path={ctx.page.slug} />
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
      {item.summary && <p className="sv-muted">{item.summary}</p>}
      {item.amenities.length > 0 && <ul className="sv-ticks">{item.amenities.slice(0, 4).map(a => <li key={a}><Check aria-hidden="true" size={18} />{a}</li>)}</ul>}
      <WaButton wa={bound(ctx, s).wa} label={`Ask about ${item.name}`} quiet />
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
