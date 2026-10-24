// v2 sections, part 1: hero, packages, itinerary, gallery. Each returns null when HAIP has nothing to show, so an empty
// section never reaches a guest (the publish checklist warns instead).
import { Check } from "lucide-react";
import { inr } from "../types";
import { bound, CallButton, Em, Head, Heading, Img, Section, WaButton, type Ctx } from "./parts";
import { txt, type Itinerary, type PackageItem, type SectionV2 } from "./types";

export function Hero(s: SectionV2, ctx: Ctx) {
  const b = bound(ctx, s);
  const media = typeof b.media === "string" ? b.media : null;
  const eyebrow = txt(s.slots.eyebrow), sub = txt(s.slots.subhead), cta = txt(s.slots.cta_label);
  const phone = ctx.live.doc.site.contact.phone;
  const H = ctx.first ? "h1" : "h2";
  const text = (
    <div className="sv-hero__text sv-rise">
      {eyebrow && <p className="sv-eyebrow">{eyebrow}</p>}
      <H className="sv-h1"><Em text={txt(s.slots.headline)} /></H>
      {sub && <p className="sv-lede">{sub}</p>}
      <div className="sv-actions"><WaButton wa={b.wa} label={cta} /><CallButton phone={phone} /></div>
    </div>
  );
  if (s.variant === "fullbleed-image") {
    return (
      <Section s={s} className={media ? "" : "sv-hero--no-media"}>
        {media && <div className="sv-hero__media"><Img ref_={media} ctx={ctx} eager sizes="100vw" /></div>}
        <div className="sv-hero__scrim" aria-hidden="true" />
        <div className="sv-wrap">{text}</div>
      </Section>
    );
  }
  if (s.variant === "split") {
    return (
      <Section s={s}>
        <div className="sv-wrap sv-hero__grid">
          {text}
          {media && <div className="sv-hero__frame"><Img ref_={media} ctx={ctx} eager sizes="(min-width: 760px) 50vw, 100vw" /></div>}
        </div>
      </Section>
    );
  }
  return (
    <Section s={s}>
      <div className="sv-wrap sv-hero__center">{text}</div>
      {media && <div className="sv-wrap sv-hero__wide"><Img ref_={media} ctx={ctx} eager sizes="100vw" /></div>}
    </Section>
  );
}

function Price({ p }: { p: PackageItem }) {
  if (!p.price) return null;
  return <p className="sv-price"><span className="sv-price__amount">{inr(p.price.amount)}</span><span className="sv-price__label">{p.price.label}</span></p>;
}

const priceCta = (p: PackageItem) => (p.price ? "Plan this on WhatsApp" : p.price_label || "Get the price on WhatsApp");
const meta = (p: PackageItem) => [p.length, p.destinations.join(" · "), p.max_guests ? `Up to ${p.max_guests} guests` : ""].filter(Boolean);

export function Packages(s: SectionV2, ctx: Ctx) {
  const items = (bound(ctx, s).items || []) as PackageItem[];
  if (!items.length) return null;
  if (s.variant === "comparison") {
    return (
      <Section s={s}>
        <div className="sv-wrap sv-rise">
          <Head ctx={ctx} s={s} />
          <table className="sv-compare">
            <thead><tr><th scope="col">Journey</th><th scope="col">Length</th><th scope="col">Route</th><th scope="col">Includes</th><th scope="col"><span className="sv-sr">Price</span></th></tr></thead>
            <tbody>
              {items.map(p => (
                <tr key={p.key}>
                  <th scope="row" data-label="Journey"><span className="sv-h3">{p.name}</span></th>
                  <td data-label="Length">{p.length}</td>
                  <td data-label="Route">{p.destinations.join(", ") || "Ask us"}</td>
                  <td data-label="Includes">{p.inclusions.slice(0, 3).join(", ") || "Ask us"}</td>
                  <td data-label="Price"><Price p={p} /><WaButton wa={p.wa} label={priceCta(p)} quiet /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>
    );
  }
  if (s.variant === "feature") {
    const [top, ...rest] = items;
    return (
      <Section s={s} band>
        <div className="sv-wrap sv-rise">
          <Head ctx={ctx} s={s} />
          <article className="sv-feature">
            <div className="sv-feature__main">
              <p className="sv-meta">{meta(top).join(" · ")}</p>
              <h3 className="sv-h2">{top.name}</h3>
              {top.summary && <p className="sv-lede">{top.summary}</p>}
              {top.inclusions.length > 0 && <ul className="sv-ticks">{top.inclusions.map(i => <li key={i}><Check aria-hidden="true" size={18} />{i}</li>)}</ul>}
            </div>
            <aside className="sv-feature__side">
              {top.days.length > 0 && <><p className="sv-eyebrow">The route</p>
                <ol className="sv-daylist">{top.days.map((d, i) => <li key={i}><span>Day {i + 1}</span>{d}</li>)}</ol></>}
              <Price p={top} />
              <WaButton wa={top.wa} label={priceCta(top)} className="sv-btn--block" />
            </aside>
          </article>
          {rest.length > 0 && (
            <ul className="sv-also">{rest.map(p => <li key={p.key}><span className="sv-h3">{p.name}</span><span className="sv-meta">{p.length}</span>
              {p.wa && <a className="sv-link" href={p.wa.href} target="_blank" rel="noopener noreferrer" data-wa-ref={p.wa.code}>{priceCta(p)}</a>}</li>)}</ul>
          )}
        </div>
      </Section>
    );
  }
  return (
    <Section s={s}>
      <div className="sv-wrap">
        <Head ctx={ctx} s={s} />
        <div className="sv-cards">
          {items.map(p => (
            <article key={p.key} className="sv-card sv-rise">
              <p className="sv-meta">{meta(p).join(" · ")}</p>
              <h3 className="sv-h3">{p.name}</h3>
              {p.summary && <p className="sv-muted">{p.summary}</p>}
              {p.inclusions.length > 0 && <ul className="sv-ticks">{p.inclusions.slice(0, 4).map(i => <li key={i}><Check aria-hidden="true" size={18} />{i}</li>)}</ul>}
              <div className="sv-card__foot"><Price p={p} /><WaButton wa={p.wa} label={priceCta(p)} className="sv-btn--block" /></div>
            </article>
          ))}
        </div>
      </div>
    </Section>
  );
}

const pad = (n: number) => String(n).padStart(2, "0");

function DayBody({ d }: { d: Itinerary["days"][number] }) {
  return (
    <>
      {d.stops.length > 0 && <p className="sv-route">{d.stops.join(" → ")}</p>}
      {d.notes && <p className="sv-muted">{d.notes}</p>}
      {d.overnight && <p className="sv-meta">Night at {d.overnight}</p>}
    </>
  );
}

export function ItinerarySection(s: SectionV2, ctx: Ctx) {
  const b = bound(ctx, s);
  const it = b.itinerary;
  if (!it || !it.days.length) return null;
  const sub = [it.destination, it.nights ? `${it.nights} night${it.nights > 1 ? "s" : ""}` : "Day trip", it.packages.length ? `Part of ${it.packages.join(", ")}` : ""].filter(Boolean).join(" · ");
  const head = (
    <header className="sv-head">
      {txt(s.slots.eyebrow) && <p className="sv-eyebrow">{txt(s.slots.eyebrow)}</p>}
      <Heading ctx={ctx} text={txt(s.slots.heading) || it.name} />
      <p className="sv-meta">{sub}</p>
      {(txt(s.slots.intro) || it.about) && <p className="sv-lede">{txt(s.slots.intro) || it.about}</p>}
    </header>
  );
  if (s.variant === "accordion") {
    return (
      <Section s={s}>
        <div className="sv-wrap sv-narrow sv-rise">
          {head}
          <div className="sv-acc">
            {it.days.map((d, i) => (
              <details key={d.day} className="sv-acc__item" open={i === 0} name={`it-${s.id}`}>
                <summary><span className="sv-acc__day">Day {pad(d.day)}</span><span className="sv-acc__title">{d.title}</span></summary>
                <div className="sv-acc__body"><DayBody d={d} /></div>
              </details>
            ))}
          </div>
          <WaButton wa={b.wa} label="Ask about this route" quiet />
        </div>
      </Section>
    );
  }
  if (s.variant === "day-cards") {
    return (
      <Section s={s} band>
        <div className="sv-wrap">
          {head}
          <ol className="sv-daycards">
            {it.days.map(d => (
              <li key={d.day} className="sv-card sv-rise"><p className="sv-daynum">{pad(d.day)}</p><h3 className="sv-h3">{d.title}</h3><DayBody d={d} /></li>
            ))}
          </ol>
        </div>
      </Section>
    );
  }
  return (
    <Section s={s}>
      <div className="sv-wrap sv-timeline-grid">
        {head}
        <ol className="sv-timeline">
          {it.days.map(d => (
            <li key={d.day} className="sv-rise"><p className="sv-daynum" aria-label={`Day ${d.day}`}>{pad(d.day)}</p>
              <div><h3 className="sv-h3">{d.title}</h3><DayBody d={d} /></div></li>
          ))}
        </ol>
      </div>
    </Section>
  );
}

export function Gallery(s: SectionV2, ctx: Ctx) {
  const media = Array.isArray(bound(ctx, s).media) ? (bound(ctx, s).media as string[]) : [];
  const shown = media.filter(m => ctx.env.assets[m.slice(6)]);
  if (!shown.length) return null;
  const cls = s.variant === "filmstrip" ? "sv-strip" : s.variant === "grid" ? "sv-grid" : "sv-masonry";
  return (
    <Section s={s}>
      <div className="sv-wrap">
        <Head ctx={ctx} s={s} />
        <ul className={cls} {...(s.variant === "filmstrip" ? { tabIndex: 0, "aria-label": txt(s.slots.heading) || "Photos" } : {})}>
          {shown.map(m => <li key={m} className="sv-rise"><Img ref_={m} ctx={ctx} sizes="(min-width: 760px) 33vw, 50vw" /></li>)}
        </ul>
      </div>
    </Section>
  );
}
