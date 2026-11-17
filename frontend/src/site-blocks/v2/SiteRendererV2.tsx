// One page of a v2 (SiteSpec) client site: header, the page's sections, footer. Server-rendered in the sites app; the
// v1 renderer (../SiteRenderer.tsx) still draws every block-based site. Theme = CSS variables computed by HAIP
// (website_spec_service.theme), so colour maths and AA checks live in one place.
import { Fragment, type CSSProperties, type ReactNode } from "react";
import { Done } from "../booking";
import { ManageBooking } from "../interactive";
import { pack, packVars } from "../packs";
import { Policies } from "../sections";
import { MessageCircle } from "lucide-react";
import { hrefOf, imageOf, inr, type LiveData, type SiteEnv } from "../types";
import { type Ctx, WaButton } from "./parts";
import { Gallery, Hero, ItinerarySection, Packages } from "./sections-a";
import { BookingCta, ContactSection, Faq, Reviews } from "./sections-b";
import { Booking, OfferSection, Stays, TextSection } from "./sections-c";
import { PackageDetails, StayBooking, StayDetails, StayGallery, StayMap, StayRules } from "./sections-t";
import { defaultTemplate, kVars, SYSTEM_PAGES, type LiveDataV2, type MenuItem, type PageV2, type SectionType, type SectionV2 } from "./types";

interface NavLink { label: string; href: string; external: boolean; current: boolean; children: NavLink[] }

/** Header and footer links: the owner's menus (website W1) when set, else every page marked nav, as before. */
function navLinks(live: LiveDataV2, page: PageV2, env: SiteEnv, which: "main" | "footer"): NavLink[] {
  const link = (it: MenuItem & { children?: MenuItem[] }): NavLink => {
    const external = it.to.startsWith("https://");
    return { label: it.label, href: external ? it.to : hrefOf(env, it.to), external, current: !external && it.to === page.slug,
      children: (it.children || []).map(link) };
  };
  const menus = live.doc.site.menus;
  if (menus) return (which === "main" ? menus.main : menus.footer).map(link);
  const pages = live.doc.pages.filter(p => p.nav && p.slug !== "/").map(p => ({ label: p.title, to: p.slug }));
  return (which === "main" ? pages : [{ label: "Home", to: "/" }, ...pages]).map(link);
}

function A({ l, className }: { l: NavLink; className?: string }) {
  return <a className={className} href={l.href} aria-current={l.current ? "page" : undefined}
    {...(l.external ? { target: "_blank", rel: "noopener noreferrer" } : {})}>{l.label}</a>;
}

const SECTIONS: Record<SectionType, (s: SectionV2, ctx: Ctx) => ReactNode> = {
  hero: Hero, stays: Stays, booking: Booking, packages: Packages, itinerary: ItinerarySection, gallery: Gallery,
  reviews: Reviews, faq: Faq, contact: ContactSection, "booking-cta": BookingCta, text: TextSection, offer: OfferSection,
  "stay-gallery": StayGallery, "stay-details": StayDetails, "stay-rules": StayRules, "stay-map": StayMap, "stay-booking": StayBooking,
  "package-details": PackageDetails,
};

/** The page a stay / package design draws (website W4): the owner's design, else the default one. Its slug ("/stays",
 * "/packages") keys the WhatsApp links the backend binds for the design (website_bindings.resolve). */
export function templatePageV2(live: LiveDataV2, key: "stay" | "package", title: string): PageV2 {
  return { slug: key === "stay" ? "/stays" : "/packages", title, nav: false, seo: { title: "", description: "" },
    sections: live.doc.templates?.[key]?.sections || defaultTemplate(key) };
}

/** A page every v2 site has (SYSTEM_PAGES) unless the spec has its own: drawn with the v1 parts, in this site's palette. */
export function systemPage(live: LiveDataV2, path: string, env: SiteEnv): { page: PageV2; main: ReactNode } | null {
  const title = SYSTEM_PAGES[path];
  if (!title) return null;
  const q = env.query || {};
  // Policies reads only live.policies, live.legal and live.doc.site.name, which a v2 bootstrap carries too.
  const body = path === "/policies" ? Policies({ id: "policies" }, { env, live: live as unknown as LiveData })
    : path === "/my-booking" ? <ManageBooking p={{ id: "manage" }} env={env} />
    : q.hold && q.s ? <Done env={env} holdId={q.hold} session={q.s} /> : null;
  if (!body) return null;
  const page: PageV2 = { slug: path, title, nav: false, seo: { title: "", description: "" }, sections: [] };
  return { page, main: <div className="hs p-calm" style={{ ...packVars(pack(undefined)), ...kVars(live) } as CSSProperties}>{body}</div> };
}

export function SiteRendererV2({ live, page, env, banner, main }: { live: LiveDataV2; page: PageV2; env: SiteEnv; banner?: ReactNode; main?: ReactNode }) {
  const doc = live.doc;
  const nav = navLinks(live, page, env, "main");
  const foot = navLinks(live, page, env, "footer");
  const wa = live.page_wa[page.slug] || null;
  const fab = live.float_wa?.[page.slug] || null;
  const brand = doc.site.brand;
  const logo = imageOf(env, brand?.logo);
  const logoDims = brand?.logo ? live.assets[brand.logo.slice(6)] : undefined;
  const c = doc.site.contact;
  const stayBar = !!env.stay && page.sections.some(s => s.type === "stay-booking");   // W5: price + Check dates pinned on phones
  const hasBar = stayBar || page.sections.some(s => s.type === "booking-cta" && s.variant === "sticky-bar");
  const overHero = page.sections[0]?.type === "hero" && ["fullbleed-image", "video"].includes(page.sections[0].variant);
  return (
    <div className={`sv${hasBar ? " sv--has-bar" : ""}${overHero ? " sv--over-hero" : ""}${fab ? " sv--has-fab" : ""}`} data-motion={live.theme.motion}
      data-scheme={live.theme.scheme} style={live.theme.vars as CSSProperties}>
      {live.theme.fonts_href && <link rel="stylesheet" href={live.theme.fonts_href} precedence="default" />}
      {!overHero && banner}
      <a className="sv-skip" href="#sv-main">Skip to content</a>
      <header className="sv-top">
        {overHero && banner /* the header floats over the photo; outside it the banner would sit under the header */}
        <div className="sv-wrap sv-top__bar">
          <a className="sv-brand" href={hrefOf(env, "/")} aria-label={logo && brand?.show_name === false ? doc.site.name : undefined}>
            {logo && (
              // eslint-disable-next-line @next/next/no-img-element
              <img className="sv-brand__logo" src={logo.src.startsWith("/_haip/media/") ? `${logo.src}?w=480` : logo.src} alt=""
                width={logoDims?.w || undefined} height={logoDims?.h || undefined} decoding="async" />
            )}
            {(!logo || brand?.show_name !== false) && <span>{doc.site.name}</span>}
          </a>
          {nav.length > 0 && (
            <nav className="sv-nav" aria-label="Main">
              {nav.map((l, i) => l.children.length ? (
                <details key={i} className="sv-drop">
                  <summary>{l.label}</summary>
                  <div className="sv-drop__panel"><A l={{ ...l, children: [] }} />{l.children.map((ch, j) => <A key={j} l={ch} />)}</div>
                </details>
              ) : <A key={i} l={l} />)}
            </nav>
          )}
          <div className="sv-top__cta">
            <WaButton wa={wa} label="WhatsApp" className="sv-btn--sm" />
            {nav.length > 0 && (
              <details className="sv-menu">
                <summary aria-label="Menu"><span /><span /></summary>
                <nav aria-label="Pages">
                  {!doc.site.menus && <a href={hrefOf(env, "/")}>Home</a>}
                  {nav.flatMap((l, i) => [<A key={i} l={l} />, ...l.children.map((ch, j) => <A key={`${i}-${j}`} l={ch} className="sv-menu__sub" />)])}
                </nav>
              </details>
            )}
          </div>
        </div>
      </header>
      <main id="sv-main">
        {main}
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
          {foot.length > 0 && <nav aria-label="Footer"><p className="sv-foot__h">Explore</p>
            {foot.map((l, i) => <A key={i} l={l} />)}</nav>}
          <div><p className="sv-foot__h">Talk to us</p>
            {wa && <a href={wa.href} target="_blank" rel="noopener noreferrer" data-wa-ref={wa.code}>WhatsApp</a>}
            {c.phone && <a href={`tel:${c.phone.replace(/[^\d+]/g, "")}`}>{c.phone}</a>}
            {c.email && <a href={`mailto:${c.email}`}>{c.email}</a>}
            {Object.entries(doc.site.social || {}).map(([k, v]) => <a key={k} href={v} target="_blank" rel="noopener noreferrer">{k[0].toUpperCase() + k.slice(1)}</a>)}
          </div>
        </div>
        <p className="sv-wrap sv-legal">© {live.legal.legal_name || doc.site.name}{live.legal.gstin ? ` · GSTIN ${live.legal.gstin}` : ""}{c.address ? ` · ${c.address}` : ""} · <a href={hrefOf(env, "/policies")}>Policies</a>{live.blog_count ? <> · <a href={hrefOf(env, "/blog")}>Guides</a></> : null} · Website by HAIP</p>
      </footer>
      {stayBar && env.stay && (
        <div className={`sv-staybar${page.sections.some(s => s.type === "booking-cta" && s.variant === "sticky-bar") ? " sv-staybar--off" : ""}`}>
          <span>{env.stay.from_price && live.site.show_prices ? <>From <b>{inr(env.stay.from_price)}</b> / night</> : env.stay.name}</span>
          <a className="sv-btn" href="#book">Check dates</a>
        </div>
      )}
      {fab && (
        <a className="sv-fab" href={fab.href} target="_blank" rel="noopener noreferrer" data-wa-ref={fab.code} aria-label="Chat with us on WhatsApp">
          <MessageCircle aria-hidden="true" size={26} strokeWidth={1.75} />
        </a>
      )}
    </div>
  );
}
