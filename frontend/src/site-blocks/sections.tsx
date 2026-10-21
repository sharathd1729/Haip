// Static site sections (no hooks: they render on the server in the sites app). Interactive pieces live in
// interactive.tsx. Every section takes its saved props plus the shared context (env + live data).
import type { ReactNode } from "react";
import { AmenityIcon } from "./icons";
import { BookingBar, BookingEngine, ContactForm, GalleryGrid, ManageBooking, PriceBox } from "./interactive";
import { arr, hrefOf, imageOf, inr, str, type LiveData, type Props, type SiteEnv, type Stay } from "./types";

export interface Ctx { env: SiteEnv; live: LiveData; first?: boolean }   // first = the page's first section: its heading is the h1

export function Em({ text }: { text: string }) {
  const parts = text.split(/\*(.+?)\*/g);
  return <>{parts.map((p, i) => (i % 2 ? <em key={i}>{p}</em> : <span key={i}>{p}</span>))}</>;
}

export function Pic({ src, env, className = "k-img", alt }: { src: unknown; env: SiteEnv; className?: string; alt?: string }) {
  const img = typeof src === "string" && src.startsWith("https://") ? { src, alt: alt || "" } : imageOf(env, src);
  // eslint-disable-next-line @next/next/no-img-element
  return img ? <img className={className} src={img.src} alt={alt ?? img.alt} loading="lazy" /> : <div className="k-ph" role="presentation" />;
}

export function linkFor(raw: unknown, ctx: Ctx): { href: string; external: boolean } | null {
  const v = str(raw);
  if (!v) return null;
  if (v.startsWith("wa:") || v === "/whatsapp") {
    const num = (ctx.live.doc.site.contact.whatsapp || ctx.live.doc.site.contact.phone || "").replace(/[^\d]/g, "");
    return num ? { href: `https://wa.me/${num}`, external: true } : null;
  }
  if (v.startsWith("https://")) return { href: v, external: true };
  if (v.startsWith("tel:") || v.startsWith("mailto:") || v.startsWith("#")) return { href: v, external: false };
  return { href: hrefOf(ctx.env, v), external: false };
}

export function Cta({ label, link, ctx, className = "k-btn" }: { label: unknown; link: unknown; ctx: Ctx; className?: string }) {
  const l = linkFor(link, ctx);
  if (!str(label) || !l) return null;
  return <a className={className} href={l.href} {...(l.external ? { target: "_blank", rel: "noopener noreferrer" } : {})}>{str(label)}</a>;
}

const Kick = ({ t }: { t: unknown }) => (str(t) ? <span className="k-kick">{str(t)}</span> : null);
const H2 = ({ t, h1 }: { t: unknown; h1?: boolean }) => (!str(t) ? null : h1 ? <h1 className="k-h2">{str(t)}</h1> : <h2 className="k-h2">{str(t)}</h2>);
const Chips = ({ items }: { items: unknown }) => {
  const list = arr<string>(items);
  return list.length ? <div className="k-chips">{list.map((c, i) => <span key={i} className="k-chip">{c}</span>)}</div> : null;
};

export function Hero(p: Props, ctx: Ctx) {
  const text = (
    <>
      <Kick t={p.kicker} />
      <h1 className="k-h1"><Em text={str(p.title)} /></h1>
      {str(p.text) && <p className="k-p">{str(p.text)}</p>}
      <Chips items={p.chips} />
      <Cta label={p.cta_label} link={p.cta_link} ctx={ctx} />
    </>
  );
  if (p.layout === "full") return <div className="k-full"><Pic src={p.image1} env={ctx.env} /><div>{text}</div></div>;
  if (p.layout === "centred") return <div className="k-sec k-center k-wrap">{text}<div className="k-wide"><Pic src={p.image1} env={ctx.env} /></div></div>;
  return (
    <div className="k-sec k-hero split k-wrap">
      <div style={{ display: "grid", gap: 14 }}>{text}</div>
      <div className="k-mosaic"><Pic src={p.image1} env={ctx.env} /><Pic src={p.image2} env={ctx.env} /><Pic src={p.image3} env={ctx.env} /></div>
    </div>
  );
}

function StayPrice({ s, live }: { s: Stay; live: LiveData }) {
  if (live.site.show_prices && s.from_price) {
    return <p className="k-price">From {inr(s.from_price)} <small>/ night{live.site.prices_include_gst ? " incl. GST" : " + GST"}</small></p>;
  }
  return <p className="k-price"><small>{live.site.booking_mode === "enquiry" ? "Ask us for prices" : "See prices for your dates"}</small></p>;
}

export function Stays(p: Props, ctx: Ctx) {
  const all = ctx.live.stays;
  const n = p.limit === "all" || !p.limit ? all.length : Number(p.limit);
  const list = all.slice(0, n);
  const href = (s: Stay) => hrefOf(ctx.env, `/stays/${s.slug}`);
  const meta = (s: Stay) => [s.sleeps ? `Sleeps ${s.sleeps}` : "", s.bedrooms ? `${s.bedrooms} bedroom${s.bedrooms > 1 ? "s" : ""}` : "", s.city].filter(Boolean).join(" · ");
  return (
    <div className="k-sec k-wrap">
      <Kick t={p.kicker} /><H2 t={p.heading} h1={ctx.first} />
      {str(p.intro) && <p className="k-p">{str(p.intro)}</p>}
      {!list.length ? <p className="k-p">Your stays from HAIP appear here.</p> : p.layout === "list" ? (
        <div style={{ display: "grid", gap: 12 }}>
          {list.map(s => (
            <a key={s.id} className="k-row" href={href(s)}>
              <div className="k-media"><Pic src={s.photos[0]} env={ctx.env} alt={s.name} /></div>
              <div className="t"><span className="k-kick">{s.type}</span><h3 className="k-h3">{s.name}</h3>
                <p className="k-small">{meta(s)}</p>{s.summary && <p className="k-p" style={{ fontSize: 15 }}>{s.summary}</p>}<StayPrice s={s} live={ctx.live} /></div>
            </a>
          ))}
        </div>
      ) : (
        <div className="k-grid3">
          {list.map(s => (
            <a key={s.id} className="k-card" href={href(s)}>
              <div className="k-media"><Pic src={s.photos[0]} env={ctx.env} alt={s.name} /></div>
              <div className="t"><span className="k-kick">{s.type}</span><h3 className="k-h3">{s.name}</h3>
                <p className="k-small">{meta(s)}</p><StayPrice s={s} live={ctx.live} /></div>
            </a>
          ))}
        </div>
      )}
    </div>
  );
}

const ICON_LABEL: Record<string, string> = {
  pool: "Pool", wifi: "Wi-Fi", kitchen: "Kitchen", parking: "Parking", ac: "Air conditioning", breakfast: "Breakfast", pets: "Pet-friendly",
  gym: "Gym", spa: "Spa", bonfire: "Bonfire", garden: "Garden", view: "Views", beach: "Beach nearby", workspace: "Workspace", tv: "TV",
  washer: "Washing machine", family: "Family-friendly", accessible: "Accessible", caravan: "Caravan", driver: "Driver included",
  mountain: "Mountains", coffee: "Coffee estate",
};

export function Amenities(p: Props, ctx: Ctx) {
  const icons = arr<string>(p.icons);
  void ctx;
  return (
    <div className="k-sec k-wrap" style={{ paddingBlock: 24 }}>
      <Kick t={p.kicker} /><H2 t={p.heading} />
      <div className="k-ams">{icons.map(k => <div key={k} className="k-am"><AmenityIcon name={k} /><span>{ICON_LABEL[k] || k}</span></div>)}</div>
    </div>
  );
}

export function Offer(p: Props, ctx: Ctx) {
  const today = ctx.live.site.today;
  if ((str(p.starts) && today < str(p.starts)) || (str(p.ends) && today > str(p.ends))) {
    return ctx.env.mode === "editor" ? <div className="k-sec k-wrap"><p className="k-small">Offer hidden today: shows {str(p.starts) || "now"} to {str(p.ends) || "always"}.</p></div> : null;
  }
  return (
    <div className="k-sec k-wrap" style={{ paddingBlock: 16 }}>
      <div className={`k-offer t-${str(p.tone) || "brand"}`}>
        <Kick t={p.kicker} /><h2 className="k-h2">{str(p.title)}</h2>
        {str(p.text) && <p className="k-p">{str(p.text)}</p>}
        <Cta label={p.cta_label} link={p.cta_link} ctx={ctx} />
      </div>
    </div>
  );
}

export function Highlights(p: Props, ctx: Ctx) {
  const items = arr<string>(p.items);
  const head = <><Kick t={p.kicker} /><H2 t={p.heading} /></>;
  if (p.layout === "grid") {
    return <div className="k-sec k-wrap">{head}<div className="k-tiles">{items.map((x, i) => <div key={i} className="k-tile">{x}</div>)}</div></div>;
  }
  const text = <div style={{ display: "grid", gap: 12 }}>{head}<ul className="k-list">{items.map((x, i) => <li key={i}>{x}</li>)}</ul></div>;
  const pic = <div className="k-side"><Pic src={p.image} env={ctx.env} /></div>;
  return <div className="k-sec k-wrap"><div className="k-split">{p.layout === "image_right" ? <>{text}{pic}</> : <>{pic}{text}</>}</div></div>;
}

const SOURCE: Record<string, string> = { google: "Google", airbnb: "Airbnb", booking: "Booking.com", tripadvisor: "Tripadvisor", direct: "Direct guest" };

export function Reviews(p: Props, ctx: Ctx) {
  const items = arr<{ quote: string; name: string; source: string; rating: string; date: string }>(p.items);
  if (!items.length) {
    return ctx.env.mode === "editor"
      ? <div className="k-sec k-wrap"><Kick t={p.kicker} /><H2 t={p.heading} /><p className="k-small">Paste reviews guests wrote on Google or Airbnb in the panel. Only real reviews.</p></div>
      : null;
  }
  return (
    <div className="k-sec k-wrap">
      <Kick t={p.kicker} /><H2 t={p.heading} />
      <div className={p.layout === "single" ? "" : "k-grid2"} style={{ gap: 22, display: "grid", marginTop: 8 }}>
        {items.map((r, i) => (
          <figure key={i} className="k-rev" style={{ margin: 0 }}>
            <span className="k-stars" aria-label={`${r.rating || 5} stars`}>{"★".repeat(Number(r.rating) || 5)}</span>
            <blockquote style={{ margin: 0 }} className="k-p">&ldquo;{r.quote}&rdquo;</blockquote>
            <figcaption className="k-small"><b>{r.name}</b>{r.source ? ` · ${SOURCE[r.source] || r.source}` : ""}{r.date ? ` · ${r.date}` : ""}</figcaption>
          </figure>
        ))}
      </div>
    </div>
  );
}

export function Gallery(p: Props, ctx: Ctx) {
  const imgs = arr<string>(p.images).map(r => imageOf(ctx.env, r)).filter(Boolean) as { src: string; alt: string }[];
  return (
    <div className="k-sec k-wrap">
      <H2 t={p.heading} />
      {imgs.length ? <GalleryGrid images={imgs} mosaic={p.layout === "mosaic"} /> : <p className="k-small">Pick photos for the gallery.</p>}
    </div>
  );
}

export function FAQ(p: Props, ctx?: Ctx) {
  const items = arr<{ q: string; a: string }>(p.items);
  return (
    <div className="k-sec k-wrap">
      <H2 t={p.heading} h1={ctx?.first} />
      <div style={{ display: "grid", gap: 8 }}>
        {items.map((f, i) => <details key={i} className="k-faq"><summary>{f.q}</summary><p>{f.a}</p></details>)}
      </div>
    </div>
  );
}

export function Text(p: Props, ctx?: Ctx) {
  return (
    <div className={`k-sec k-wrap ${p.layout === "centred" ? "k-center" : ""}`}>
      <Kick t={p.kicker} />
      <H2 t={p.heading} h1={ctx?.first} />
      {str(p.body).split(/\n{2,}/).filter(Boolean).map((para, i) => <p key={i} className="k-p" style={{ fontSize: 17 }}>{para}</p>)}
    </div>
  );
}

export function Contact(p: Props, ctx: Ctx) {
  const c = ctx.live.doc.site.contact;
  const wa = linkFor("wa:", ctx);
  return (
    <div className="k-sec k-wrap">
      <div className="k-split" style={{ alignItems: "start" }}>
        <div style={{ display: "grid", gap: 12 }}>
          <H2 t={p.heading} h1={ctx.first} />
          {str(p.text) && <p className="k-p">{str(p.text)}</p>}
          {wa && <a className="k-btn alt" href={wa.href} target="_blank" rel="noopener noreferrer">WhatsApp us</a>}
          <p className="k-small">
            {c.phone && <>Call <a href={`tel:${c.phone.replace(/\s/g, "")}`}>{c.phone}</a><br /></>}
            {c.email && <>Email <a href={`mailto:${c.email}`}>{c.email}</a><br /></>}
            {c.address}
          </p>
        </div>
        {p.show_form ? <ContactForm env={ctx.env} stays={ctx.live.stays} /> : null}
      </div>
    </div>
  );
}

export function Location(p: Props, ctx: Ctx) {
  const items = arr<{ place: string; time: string }>(p.items);
  const map = linkFor(p.map_link, ctx);
  return (
    <div className="k-sec k-wrap">
      <H2 t={p.heading} />
      {str(p.text) && <p className="k-p">{str(p.text)}</p>}
      {str(p.address) && <p><b>{str(p.address)}</b></p>}
      {items.length > 0 && <table className="k-table"><tbody>{items.map((r, i) => <tr key={i}><td>{r.place}</td><td className="r">{r.time}</td></tr>)}</tbody></table>}
      {map && <a className="k-link" href={map.href} target="_blank" rel="noopener noreferrer">Open in Google Maps</a>}
    </div>
  );
}

export function Band(p: Props, ctx: Ctx) {
  return (
    <div className="k-sec k-wrap">
      <Kick t={p.kicker} /><h2 className="k-h2">{str(p.heading)}</h2>
      {str(p.text) && <p className="k-p">{str(p.text)}</p>}
      <Chips items={p.chips} />
      <Cta label={p.cta_label} link={p.cta_link} ctx={ctx} />
    </div>
  );
}

export function StayDetail(p: Props, ctx: Ctx) {
  const s = ctx.env.stay || ctx.live.stays[0];
  if (!s) return <div className="k-sec k-wrap"><p className="k-p">Add a property in HAIP to fill this page.</p></div>;
  const facts = [s.sleeps ? `${s.sleeps} guests` : "", s.bedrooms ? `${s.bedrooms} bedroom${s.bedrooms > 1 ? "s" : ""}` : "",
    s.bathrooms ? `${s.bathrooms} bath` : "", ctx.live.policies.stay_rules ? `Check-in ${ctx.live.policies.stay_rules.check_in_time} · out ${ctx.live.policies.stay_rules.check_out_time}` : ""].filter(Boolean);
  const photos = s.photos.map(u => ({ src: u, alt: s.name }));
  return (
    <div className="k-sec k-wrap">
      <span className="k-kick">{s.type}{s.city ? ` · ${s.city}` : ""}</span>
      <h1 className="k-h1">{s.name}</h1>
      {photos.length ? <GalleryGrid images={photos.slice(0, 7)} mosaic /> : <div className="k-wide"><div className="k-ph" /></div>}
      <p className="k-small">{facts.join(" · ")}</p>
      <div className="k-layout">
        <div style={{ display: "grid", gap: 16 }}>
          {str(p.intro) && <p style={{ fontSize: 18 }}>{str(p.intro)}</p>}
          {(s.description || "").split(/\n{2,}/).filter(Boolean).map((t, i) => <p key={i} className="k-p">{t}</p>)}
          {s.amenities.length > 0 && <><h2 className="k-h2" style={{ fontSize: 28 }}>What&apos;s included</h2>
            <ul className="k-list" style={{ columns: 2 }}>{s.amenities.map(a => <li key={a}>{a}</li>)}</ul></>}
          {(s.faqs || []).length > 0 && <div style={{ display: "grid", gap: 8 }}>{(s.faqs || []).map((f, i) => <details key={i} className="k-faq"><summary>{f.q}</summary><p>{f.a}</p></details>)}</div>}
        </div>
        <PriceBox env={ctx.env} live={ctx.live} stay={s} />
      </div>
    </div>
  );
}

function refundTable(live: LiveData): ReactNode {
  const tiers = [...(live.policies.cancellation_policy?.tiers || [])].sort((a, b) => b.days_before - a.days_before);
  if (!tiers.length) return <p className="k-p">Cancellation terms are shared before you pay.</p>;
  return (
    <table className="k-table"><thead><tr><th>If you cancel</th><th className="r">Refund</th></tr></thead><tbody>
      {tiers.map((t, i) => <tr key={i}><td>{t.days_before === 0 ? "On the day of arrival" : `${t.days_before} or more days before arrival`}</td><td className="r">{t.refund_percent}%</td></tr>)}
    </tbody></table>
  );
}

export function Policies(p: Props, ctx: Ctx) {
  const { live } = ctx;
  const pay = live.policies.payment_policy;
  const rules = live.policies.stay_rules;
  const name = live.legal.legal_name || live.doc.site.name;
  return (
    <div className="k-sec k-wrap">
      <h1 className="k-h1" style={{ fontSize: 40 }}>{str(p.heading) || "Policies"}</h1>
      <h2 className="k-h2" style={{ fontSize: 26 }}>Cancellation and refunds</h2>{refundTable(live)}
      <p className="k-p">Refunds go back to the original payment method within 5 to 7 working days.</p>
      {pay && <><h2 className="k-h2" style={{ fontSize: 26 }}>Payments</h2>
        <p className="k-p">{pay.advance_percent}% is due to confirm a booking; the balance is due {pay.balance_due_days_before_checkin} days before arrival. Payments are processed securely by Razorpay.</p></>}
      {rules && <><h2 className="k-h2" style={{ fontSize: 26 }}>House rules</h2>
        <ul className="k-list"><li>Check-in from {rules.check_in_time}, check-out by {rules.check_out_time}.</li>
          {rules.id_required && <li>Government photo ID for every adult guest. Foreign guests: passport and visa.</li>}
          {(rules.house_rules || []).map((r, i) => <li key={i}>{r}</li>)}</ul></>}
      {str(p.extra) && <p className="k-p" style={{ whiteSpace: "pre-line" }}>{str(p.extra)}</p>}
      <h2 className="k-h2" style={{ fontSize: 26 }}>Service delivery</h2>
      <p className="k-p">Your booking is confirmed on payment and the stay is provided on the booked dates at the listed address. Nothing is shipped.</p>
      <h2 className="k-h2" style={{ fontSize: 26 }}>Terms and privacy</h2>
      <p className="k-p">This website is operated by {name}{live.legal.address ? `, ${live.legal.address}` : ""}{live.legal.gstin ? ` (GSTIN ${live.legal.gstin})` : ""}.
        We collect only what your booking and the law need: your name, phone, email and stay details, used to confirm and manage your stay
        and, if you agree, to send occasional offers. You can withdraw consent or ask us to delete your data any time by contacting us.
        We don&apos;t use advertising cookies on this site.</p>
    </div>
  );
}

export const SECTIONS: Record<string, (p: Props, ctx: Ctx) => ReactNode> = {
  Hero, Stays, Amenities, Offer, Highlights, Reviews, Gallery, FAQ, Text, Contact, Location, Band,
  StayDetail, Policies,
  BookingBar: (p, ctx) => <BookingBar p={p} env={ctx.env} live={ctx.live} />,
  BookingEngine: (p, ctx) => <BookingEngine p={p} env={ctx.env} live={ctx.live} />,
  ManageBooking: (p, ctx) => <ManageBooking p={p} env={ctx.env} />,
};
