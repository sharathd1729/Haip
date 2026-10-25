// The link-in-bio page (/links, agency M6): the business's latest Instagram posts, each linking to this website with
// that post's utm_campaign, so an enquiry or booking from it traces back to the post. Same look as the site (pack).
// "Packages": published retail packages with their day-by-day plan and an "Enquire on WhatsApp" link whose prefilled text names
// the package (the AI ties the enquiry to it). A price shows only when the business publishes prices in chat (grounded).
import type { CSSProperties } from "react";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { PageView } from "@/components/PageView";
import { apiRoot, getLive } from "@/lib/haip";
import { pack, packVars } from "@/site-blocks/packs";
import { isV2, kVars } from "@/site-blocks/v2/types";

type Params = { host: string };
interface Pkg { key: string; name: string; summary: string; length: string; days: string[]; price: string | null; whatsapp_url: string | null }
interface Links {
  name: string; book_url: string; items: { title: string; kind: string; permalink: string | null; url: string }[];
  packages?: Pkg[];
}

async function getLinks(host: string): Promise<Links | null> {
  const r = await fetch(`${apiRoot()}/public/sites/${encodeURIComponent(host)}/links`, { next: { revalidate: 300, tags: [`site:${host}`] } });
  return r.ok ? r.json() : null;
}

export async function generateMetadata({ params }: { params: Promise<Params> }): Promise<Metadata> {
  const { host } = await params;
  const live = await getLive(host);
  return live ? { title: `${live.doc.site.name}: links`, robots: { index: false } } : { title: "Not found" };
}

export default async function LinksPage({ params }: { params: Promise<Params> }) {
  const { host } = await params;
  const [live, links] = await Promise.all([getLive(host), getLinks(host)]);
  if (!live || !links) notFound();
  const doc = live.doc;
  const v2 = isV2(live) ? live : null;       // a v2 site keeps its own palette and faces here too
  const style = isV2(live) ? { ...packVars(pack(undefined)), ...kVars(live) } : packVars(pack(live.doc.theme.pack));
  return (
    <div className={`hs p-${isV2(live) ? "calm" : live.doc.theme.personality}`} style={style as CSSProperties}>
      {v2 && <link rel="stylesheet" href={v2.theme.fonts_href} precedence="default" />}
      <main className="k-wrap" style={{ maxWidth: 520, padding: "40px 20px 64px", display: "grid", gap: 14 }}>
        <h1 className="k-h">{links.name}</h1>
        {doc.site.tagline && <p className="k-p">{doc.site.tagline}</p>}
        <a className="k-btn" href={links.book_url} style={{ justifySelf: "stretch" }}>Check dates and book</a>
        {links.items.map(i => (
          <div key={i.url} className="k-card" style={{ display: "grid", gap: 8, padding: 16 }}>
            <strong>{i.title}</strong>
            <span style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              <a className="k-btn alt" href={i.url}>See dates for this</a>
              {i.permalink && <a className="k-btn alt" href={i.permalink} rel="noopener noreferrer">View the post</a>}
            </span>
          </div>
        ))}
        {!links.items.length && <p className="k-p">New posts will appear here.</p>}
        {(links.packages ?? []).length > 0 && <h2 className="k-h" style={{ fontSize: "1.25rem", marginTop: 12 }}>Packages</h2>}
        {(links.packages ?? []).map(p => (
          <div key={p.key} id={`pkg-${p.key}`} className="k-card" style={{ display: "grid", gap: 8, padding: 16 }}>
            <strong>{p.name}</strong>
            <span className="k-p" style={{ margin: 0 }}>{p.length}{p.price ? ` · ${p.price}` : ""}</span>
            {p.summary && <p className="k-p" style={{ margin: 0 }}>{p.summary}</p>}
            {p.days.length > 0 && (
              <ol style={{ margin: 0, paddingLeft: 20, display: "grid", gap: 2 }}>
                {p.days.map((d, i) => <li key={i} className="k-p" style={{ margin: 0 }}>Day {i + 1}: {d}</li>)}
              </ol>
            )}
            {p.whatsapp_url && (
              <a className="k-btn" href={p.whatsapp_url} rel="noopener noreferrer" style={{ justifySelf: "start" }}>Enquire on WhatsApp</a>
            )}
          </div>
        ))}
      </main>
      <PageView path="/links" />
    </div>
  );
}
