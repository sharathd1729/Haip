// One page of a v2 (SiteSpec) client site: header, the page's sections, footer. Server-rendered in the sites app; the
// v1 renderer (../SiteRenderer.tsx) still draws every block-based site. Theme = CSS variables computed by HAIP
// (website_spec_service.theme), so colour maths and AA checks live in one place.
import { Fragment, type CSSProperties, type ReactNode } from "react";
import { hrefOf, type SiteEnv } from "../types";
import { type Ctx, WaButton } from "./parts";
import { Gallery, Hero, ItinerarySection, Packages } from "./sections-a";
import { BookingCta, ContactSection, Faq, Reviews } from "./sections-b";
import { Booking, Stays, TextSection } from "./sections-c";
import type { LiveDataV2, PageV2, SectionType, SectionV2 } from "./types";

const SECTIONS: Record<SectionType, (s: SectionV2, ctx: Ctx) => ReactNode> = {
  hero: Hero, stays: Stays, booking: Booking, packages: Packages, itinerary: ItinerarySection, gallery: Gallery,
  reviews: Reviews, faq: Faq, contact: ContactSection, "booking-cta": BookingCta, text: TextSection,
};

export function SiteRendererV2({ live, page, env, banner }: { live: LiveDataV2; page: PageV2; env: SiteEnv; banner?: ReactNode }) {
  const doc = live.doc;
  const nav = doc.pages.filter(p => p.nav && p.slug !== "/");
  const wa = live.page_wa[page.slug] || null;
  const c = doc.site.contact;
  const hasBar = page.sections.some(s => s.type === "booking-cta" && s.variant === "sticky-bar");
  const overHero = page.sections[0]?.type === "hero" && page.sections[0].variant === "fullbleed-image";
  return (
    <div className={`sv${hasBar ? " sv--has-bar" : ""}${overHero ? " sv--over-hero" : ""}`} data-motion={live.theme.motion}
      data-scheme={live.theme.scheme} style={live.theme.vars as CSSProperties}>
      <link rel="stylesheet" href={live.theme.fonts_href} precedence="default" />
      {banner}
      <a className="sv-skip" href="#sv-main">Skip to content</a>
      <header className="sv-top">
        <div className="sv-wrap sv-top__bar">
          <a className="sv-brand" href={hrefOf(env, "/")}>{doc.site.name}</a>
          {nav.length > 0 && (
            <nav className="sv-nav" aria-label="Main">
              {nav.map(p => <a key={p.slug} href={hrefOf(env, p.slug)} aria-current={p.slug === page.slug ? "page" : undefined}>{p.title}</a>)}
            </nav>
          )}
          <div className="sv-top__cta">
            <WaButton wa={wa} label="WhatsApp" className="sv-btn--sm" />
            {nav.length > 0 && (
              <details className="sv-menu">
                <summary aria-label="Menu"><span /><span /></summary>
                <nav aria-label="Pages">{[{ slug: "/", title: "Home" }, ...nav].map(p => <a key={p.slug} href={hrefOf(env, p.slug)}>{p.title}</a>)}</nav>
              </details>
            )}
          </div>
        </div>
      </header>
      <main id="sv-main">
        {page.sections.map((s, i) => {
          const render = SECTIONS[s.type];
          return render ? <Fragment key={s.id}>{render(s, { env, live, page, first: i === 0 })}</Fragment> : null;
        })}
      </main>
      <footer className="sv-foot">
        <div className="sv-wrap sv-foot__grid">
          <div className="sv-foot__brand">
            <p className="sv-brand">{doc.site.name}</p>
            {doc.site.tagline && <p>{doc.site.tagline}</p>}
          </div>
          {nav.length > 0 && <nav aria-label="Footer"><p className="sv-foot__h">Explore</p>
            {[{ slug: "/", title: "Home" }, ...nav].map(p => <a key={p.slug} href={hrefOf(env, p.slug)}>{p.title}</a>)}</nav>}
          <div><p className="sv-foot__h">Talk to us</p>
            {wa && <a href={wa.href} target="_blank" rel="noopener noreferrer" data-wa-ref={wa.code}>WhatsApp</a>}
            {c.phone && <a href={`tel:${c.phone.replace(/[^\d+]/g, "")}`}>{c.phone}</a>}
            {c.email && <a href={`mailto:${c.email}`}>{c.email}</a>}
            {Object.entries(doc.site.social || {}).map(([k, v]) => <a key={k} href={v} target="_blank" rel="noopener noreferrer">{k[0].toUpperCase() + k.slice(1)}</a>)}
          </div>
        </div>
        <p className="sv-wrap sv-legal">© {live.legal.legal_name || doc.site.name}{live.legal.gstin ? ` · GSTIN ${live.legal.gstin}` : ""}{c.address ? ` · ${c.address}` : ""} · Website by HAIP</p>
      </footer>
    </div>
  );
}
