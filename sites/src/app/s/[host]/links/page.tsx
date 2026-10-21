// The link-in-bio page (/links, agency M6): the business's latest Instagram posts, each linking to this website with
// that post's utm_campaign, so an enquiry or booking from it traces back to the post. Same look as the site (pack).
import type { CSSProperties } from "react";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { PageView } from "@/components/PageView";
import { apiRoot, getLive } from "@/lib/haip";
import { pack, packVars } from "@/site-blocks/packs";

type Params = { host: string };
interface Links { name: string; book_url: string; items: { title: string; kind: string; permalink: string | null; url: string }[] }

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
  const p = pack(doc.theme.pack);
  return (
    <div className={`hs p-${doc.theme.personality}`} style={packVars(p) as CSSProperties}>
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
      </main>
      <PageView path="/links" />
    </div>
  );
}
