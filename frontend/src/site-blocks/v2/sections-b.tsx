// v2 sections, part 2: reviews, FAQ, contact, booking call to action.
import { Mail, MapPin, MessageCircle, Phone } from "lucide-react";
import { ContactForm } from "../interactive";
import { bound, CallButton, Head, Section, Stars, WaButton, type Ctx } from "./parts";
import { txt, type Review, type SectionV2 } from "./types";

const SOURCE: Record<string, string> = { google: "Google", airbnb: "Airbnb", booking: "Booking.com", tripadvisor: "Tripadvisor", direct: "Direct" };
const by = (r: Review) => [r.name, SOURCE[r.source] || r.source, r.date].filter(Boolean).join(" · ");

export function Reviews(s: SectionV2, ctx: Ctx) {
  const b = bound(ctx, s);
  const items = (b.items || []) as Review[];
  if (!items.length && !b.average) return null;
  if (s.variant === "rating-strip") {
    return (
      <Section s={s} band>
        <div className="sv-wrap sv-strip-rating sv-rise">
          {b.average ? (
            <p className="sv-rating"><span className="sv-rating__num">{b.average.toFixed(1)}</span>
              <span><Stars n={b.average} /><span className="sv-meta">{b.count} guest review{b.count === 1 ? "" : "s"}</span></span></p>
          ) : null}
          <ul className="sv-snips">{items.slice(0, 3).map((r, i) => (
            <li key={i}><q>{r.quote.length > 150 ? r.quote.slice(0, 147).trimEnd() + "…" : r.quote}</q><span className="sv-meta">{r.name}</span></li>
          ))}</ul>
        </div>
      </Section>
    );
  }
  if (s.variant === "grid") {
    return (
      <Section s={s}>
        <div className="sv-wrap">
          <Head ctx={ctx} s={s} />
          <ul className="sv-cards">{items.map((r, i) => (
            <li key={i} className="sv-card sv-rise"><Stars n={r.rating} /><blockquote className="sv-quote--sm">{r.quote}</blockquote><p className="sv-meta">{by(r)}</p></li>
          ))}</ul>
        </div>
      </Section>
    );
  }
  return (
    <Section s={s} band>
      <div className="sv-wrap">
        <Head ctx={ctx} s={s} />
        <ul className="sv-carousel" tabIndex={0} aria-label={txt(s.slots.heading) || "Guest reviews"}>
          {items.map((r, i) => (
            <li key={i} className="sv-slide">
              <figure><blockquote className="sv-quote"><Stars n={r.rating} /><p>{r.quote}</p></blockquote><figcaption className="sv-meta">{by(r)}</figcaption></figure>
            </li>
          ))}
        </ul>
      </div>
    </Section>
  );
}

export function Faq(s: SectionV2, ctx: Ctx) {
  const items = (bound(ctx, s).items || []) as { q: string; a: string }[];
  if (!items.length) return null;
  if (s.variant === "compact") {
    return (
      <Section s={s}>
        <div className="sv-wrap sv-rise">
          <Head ctx={ctx} s={s} />
          <dl className="sv-qa">{items.map((f, i) => <div key={i}><dt>{f.q}</dt><dd>{f.a}</dd></div>)}</dl>
        </div>
      </Section>
    );
  }
  const list = (
    <div className="sv-acc">
      {items.map((f, i) => (
        <details key={i} className="sv-acc__item">
          <summary><span className="sv-acc__title">{f.q}</span></summary>
          <div className="sv-acc__body"><p>{f.a}</p></div>
        </details>
      ))}
    </div>
  );
  if (s.variant === "two-column") {
    return (
      <Section s={s} band>
        <div className="sv-wrap sv-faq2 sv-rise"><div className="sv-faq2__side"><Head ctx={ctx} s={s} />
          <WaButton wa={bound(ctx, s).wa} label="Ask us anything" quiet /></div>{list}</div>
      </Section>
    );
  }
  return <Section s={s}><div className="sv-wrap sv-narrow sv-rise"><Head ctx={ctx} s={s} />{list}</div></Section>;
}

const mapUrl = (address: string) => `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(address)}`;

export function ContactSection(s: SectionV2, ctx: Ctx) {
  const c = ctx.live.doc.site.contact;
  const wa = bound(ctx, s).wa;
  if (!c.phone && !c.email && !wa && !c.address) return null;
  const rows = (
    <ul className="sv-rows">
      {wa && <li><MessageCircle aria-hidden="true" size={20} /><a href={wa.href} target="_blank" rel="noopener noreferrer" data-wa-ref={wa.code}>WhatsApp {c.whatsapp || c.phone}</a></li>}
      {c.phone && <li><Phone aria-hidden="true" size={20} /><a href={`tel:${c.phone.replace(/[^\d+]/g, "")}`}>{c.phone}</a></li>}
      {c.email && <li><Mail aria-hidden="true" size={20} /><a href={`mailto:${c.email}`}>{c.email}</a></li>}
      {c.address && <li><MapPin aria-hidden="true" size={20} /><span>{c.address}</span></li>}
    </ul>
  );
  const map = s.slots.show_map !== false && c.address ? (
    <div className="sv-map">
      <MapPin aria-hidden="true" size={28} className="sv-map__pin" />
      <p className="sv-h3">{c.address}</p>
      <a className="sv-btn sv-btn--quiet" href={mapUrl(c.address)} target="_blank" rel="noopener noreferrer">Get directions</a>
    </div>
  ) : null;
  if (s.variant === "minimal") {
    return (
      <Section s={s}>
        <div className="sv-wrap sv-contact-min sv-rise"><Head ctx={ctx} s={s} />{rows}</div>
      </Section>
    );
  }
  if (s.variant === "card") {
    return (
      <Section s={s} band>
        <div className="sv-wrap sv-narrow sv-rise">
          <div className="sv-card sv-contact-card"><Head ctx={ctx} s={s} center />{rows}
            <div className="sv-actions sv-actions--center"><WaButton wa={wa} label="Message us" /><CallButton phone={c.phone} /></div></div>
        </div>
      </Section>
    );
  }
  return (
    <Section s={s}>
      <div className="sv-wrap sv-split sv-rise"><div><Head ctx={ctx} s={s} />{rows}</div>{map}</div>
    </Section>
  );
}

export function BookingCta(s: SectionV2, ctx: Ctx) {
  const b = bound(ctx, s);
  const label = txt(s.slots.cta_label);
  const phone = ctx.live.doc.site.contact.phone;
  if (!b.wa && !phone && s.variant !== "inline-form") return null;
  if (s.variant === "inline-form") {
    return (
      <Section s={s} band>
        <div className="sv-wrap sv-split sv-rise">
          <div><Head ctx={ctx} s={s} /><div className="sv-actions"><WaButton wa={b.wa} label={label} quiet /></div></div>
          <div className="hs sv-form"><ContactForm env={ctx.env} stays={[]} /></div>
        </div>
      </Section>
    );
  }
  if (s.variant === "sticky-bar") {
    return (
      <Section s={s}>
        <div className="sv-wrap sv-cta-line sv-rise"><Head ctx={ctx} s={s} /><div className="sv-actions"><WaButton wa={b.wa} label={label} /><CallButton phone={phone} /></div></div>
        <div className="sv-stickybar" role="complementary" aria-label="Quick contact">
          <WaButton wa={b.wa} label="WhatsApp" /><CallButton phone={phone} />
        </div>
      </Section>
    );
  }
  return (
    <Section s={s} className="sv-inverse">
      <div className="sv-wrap sv-banner sv-rise"><Head ctx={ctx} s={s} /><div className="sv-actions"><WaButton wa={b.wa} label={label} /><CallButton phone={phone} /></div></div>
    </Section>
  );
}
