// One page of a client site: header, the page's sections, footer. Used by the sites app (server) and the HAIP
// editor canvas (client, with selection). The editor passes onSelect/selectedId/flash; the live site never does.
import type { CSSProperties, ReactNode } from "react";
import { MobileMenu } from "./menu";
import { pack, packVars } from "./packs";
import { linkFor, Pic, SECTIONS, type Ctx } from "./sections";
import { hrefOf, SPEC, type LiveData, type Page, type SiteEnv } from "./types";

export interface Selection {
  selectedId?: string | null;
  flash?: Set<string>;
  onSelect?: (blockId: string) => void;
}

export function findPage(live: LiveData, path: string): { page: Page; slug?: string } | null {
  const clean = ("/" + path.replace(/^\/+|\/+$/g, "")).toLowerCase();
  const exact = live.doc.pages.find(p => p.path === clean);
  if (exact && exact.key !== "stay") return { page: exact };
  const m = clean.match(/^\/stays\/([a-z0-9-]+)$/);
  const tmpl = live.doc.pages.find(p => p.key === "stay");
  if (m && tmpl && live.stays.some(s => s.slug === m[1])) return { page: tmpl, slug: m[1] };
  return null;
}

export function SiteRenderer({ live, page, env, sel, banner }: { live: LiveData; page: Page; env: SiteEnv; sel?: Selection; banner?: ReactNode }) {
  const doc = live.doc;
  const p = pack(doc.theme.pack);
  const ctx: Ctx = { env, live };
  const nav = doc.pages.filter(x => x.nav && x.key !== "stay");
  const wa = linkFor("wa:", ctx);
  const bookable = live.site.booking_mode !== "enquiry" && doc.pages.some(x => x.key === "book");
  const bookHref = hrefOf(env, bookable ? "/book" : "/contact");
  const editor = env.mode === "editor";
  return (
    <div className={`hs p-${doc.theme.personality}${editor ? " in-editor" : ""}`} style={packVars(p) as CSSProperties}>
      {banner}
      <header className="k-head">
        <div className="k-nav k-wrap">
          <a className="k-logo" href={hrefOf(env, "/")}>
            {doc.site.logo ? <Pic src={doc.site.logo} env={env} className="" alt={doc.site.name} /> : <span>{doc.site.name}</span>}
          </a>
          <nav className="k-links" aria-label="Main">
            {nav.map(x => <a key={x.id} href={hrefOf(env, x.path)} aria-current={x.id === page.id ? "page" : undefined}>{x.title}</a>)}
          </nav>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <a className="k-btn" style={{ minHeight: 40 }} href={bookHref}>{bookable ? "Book" : "Enquire"}</a>
            <MobileMenu links={nav.map(x => ({ href: hrefOf(env, x.path), title: x.title }))} />
          </div>
        </div>
        <div className="k-band" role="presentation" />
      </header>
      <main>
        {page.content.map((b, i) => {
          const render = SECTIONS[b.type];
          if (!render) return null;
          const bg = b.props.background && b.props.background !== "page" ? `bg-${b.props.background}` : "";
          const node = render(b.props, { ...ctx, first: i === 0 });
          if (!sel?.onSelect) return node ? <section key={b.props.id} className={bg} id={b.props.id}>{node}</section> : null;
          const spec = SPEC.blocks[b.type];
          const selected = sel.selectedId === b.props.id;
          return (
            <section key={b.props.id} className={`${bg} hs-edit${selected ? " is-on" : ""}${sel.flash?.has(b.props.id) ? " is-flash" : ""}`}
              data-label={`${spec?.label || b.type}${spec?.live ? " · live" : ""}`} id={b.props.id}
              onClickCapture={e => { e.preventDefault(); e.stopPropagation(); sel.onSelect!(b.props.id); }}>
              {node || <div className="k-sec k-wrap"><p className="k-small">{spec?.label}: nothing to show yet.</p></div>}
            </section>
          );
        })}
      </main>
      <footer className="k-foot">
        <div className="k-wrap" style={{ display: "grid", gap: 22 }}>
          <div className="k-fgrid">
            <div style={{ display: "grid", gap: 8 }}>
              <span className="k-logo">{doc.site.name}</span>
              {doc.site.tagline && <p style={{ opacity: .8 }}>{doc.site.tagline}</p>}
              <p style={{ opacity: .8 }}>{doc.site.contact.address}</p>
            </div>
            <div><b>Stay</b>{nav.slice(0, 5).map(x => <div key={x.id}><a href={hrefOf(env, x.path)}>{x.title}</a></div>)}</div>
            <div><b>Contact</b>
              {doc.site.contact.phone && <div><a href={`tel:${doc.site.contact.phone.replace(/\s/g, "")}`}>{doc.site.contact.phone}</a></div>}
              {doc.site.contact.email && <div><a href={`mailto:${doc.site.contact.email}`}>{doc.site.contact.email}</a></div>}
              {wa && <div><a href={wa.href} target="_blank" rel="noopener noreferrer">WhatsApp</a></div>}
              {Object.entries(doc.site.social || {}).map(([k, v]) => <div key={k}><a href={v} target="_blank" rel="noopener noreferrer">{k[0].toUpperCase() + k.slice(1)}</a></div>)}
            </div>
            <div><b>Good to know</b>
              <div><a href={hrefOf(env, "/policies")}>Cancellation and refunds</a></div>
              <div><a href={hrefOf(env, "/policies")}>Terms and privacy</a></div>
              <div><a href={hrefOf(env, "/my-booking")}>My booking</a></div>
            </div>
          </div>
          <p className="k-legal">© {live.legal.legal_name || doc.site.name}{live.legal.gstin ? ` · GSTIN ${live.legal.gstin}` : ""} · Website by HAIP</p>
        </div>
      </footer>
      <div className="k-sticky">
        {wa && <a className="k-btn alt" href={wa.href} target="_blank" rel="noopener noreferrer">WhatsApp</a>}
        <a className="k-btn" href={bookHref}>{bookable ? "Check dates" : "Enquire"}</a>
      </div>
    </div>
  );
}
