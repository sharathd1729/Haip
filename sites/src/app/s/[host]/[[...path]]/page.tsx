// A page of a live client site. Data is cached for 5 minutes and refreshed at once when HAIP publishes (revalidate).
// A published version is either a v1 block document (SiteRenderer) or a v2 SiteSpec (SiteRendererV2); isV2 picks.
// A v2 site also answers /policies, /book/done (Razorpay's return) and /my-booking (systemPage) when its spec has no such page.
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Consent } from "@/components/Consent";
import { PageView } from "@/components/PageView";
import { V1Fonts } from "@/components/V1Fonts";
import { type AnyLive, envFor, getBlog, getLive, getStay, queryOf } from "@/lib/haip";
import { type Article, ArticleView, type BlogItem, BlogList } from "@/site-blocks/v2/blog";
import { findPage, SiteRenderer } from "@/site-blocks/SiteRenderer";
import type { LiveData, Page, Stay } from "@/site-blocks/types";
import { SiteRendererV2, systemPage } from "@/site-blocks/v2/SiteRendererV2";
import { findPageV2, isV2, SYSTEM_PAGES, type LiveDataV2, type PageV2 } from "@/site-blocks/v2/types";

type Params = { host: string; path?: string[] };
type Search = Record<string, string | string[] | undefined>;
type Found =
  | { v2: false; live: LiveData; page: Page; slug?: string; stay: Stay | null }
  | { v2: true; live: LiveDataV2; page: PageV2; stay: null; system?: boolean; blog?: { items?: BlogItem[]; article?: Article } };

async function resolve(host: string, path: string[] | undefined): Promise<Found | null> {
  const live: AnyLive | null = await getLive(host);
  if (!live) return null;
  const p = "/" + (path || []).join("/");
  if (isV2(live)) {
    const page = findPageV2(live, p);
    if (page) return { v2: true, live, page, stay: null };
    const low = p.toLowerCase();
    if (low === "/blog" || low.startsWith("/blog/")) {                 // guides (website phase 5)
      const slug = low.slice(6);
      const data = await getBlog(host, slug || undefined);
      if (!data) return null;
      const a = slug ? (data as Article) : null;
      return { v2: true, live, stay: null, system: true, blog: a ? { article: a } : { items: (data as { items: BlogItem[] }).items },
        page: { slug: low, title: a ? a.title : "Guides", nav: false, sections: [],
          seo: { title: a ? `${a.title} · ${live.doc.site.name}`.slice(0, 70) : `Guides · ${live.doc.site.name}`.slice(0, 70),
            description: a ? (a.seo_description || a.excerpt) : `Trip ideas and practical guides from ${live.doc.site.name}.` } } };
    }
    const title = SYSTEM_PAGES[p.toLowerCase()];
    return title ? { v2: true, live, stay: null, system: true,
      page: { slug: p.toLowerCase(), title, nav: false, seo: { title: "", description: "" }, sections: [] } } : null;
  }
  const found = findPage(live, p);
  if (!found) return null;
  const stay = found.slug ? await getStay(host, found.slug) : null;
  return { v2: false, live, page: found.page, slug: found.slug, stay };
}

function jsonLd(r: Found, host: string): object | object[] {
  if (r.v2 && r.blog?.article) {
    const a = r.blog.article;
    return [...(r.live.jsonld?.["/"] || []).slice(0, 1), { "@context": "https://schema.org", "@type": "BlogPosting", headline: a.title,
      description: a.excerpt, datePublished: a.date || undefined, url: `https://${host}/blog/${a.slug}`,
      image: a.media ? `https://${host}/_haip/media/${a.media}` : undefined, publisher: { "@id": `https://${host}/#business` } }];
  }
  if (r.v2) return r.live.jsonld?.[r.page.slug] || r.live.jsonld?.["/"] || [];   // built by HAIP (website_seo) from the page's own data
  const c = r.live.doc.site.contact;
  const stay = r.stay;
  return {
    "@context": "https://schema.org", "@type": stay ? "HotelRoom" : "LodgingBusiness",
    name: stay ? stay.name : r.live.doc.site.name, url: `https://${host}`, telephone: c.phone || undefined, email: c.email || undefined,
    address: c.address ? { "@type": "PostalAddress", streetAddress: c.address, addressCountry: "IN" } : undefined,
    ...(stay ? { occupancy: { "@type": "QuantitativeValue", maxValue: stay.sleeps } } : {}),
  };
}

export async function generateMetadata({ params }: { params: Promise<Params> }): Promise<Metadata> {
  const { host, path } = await params;
  const r = await resolve(host, path);
  if (!r) return { title: "Not found" };
  const firstAsset = Object.keys(r.live.assets)[0];
  const image = r.stay?.photos[0] ? [r.stay.photos[0]] : firstAsset ? [`https://${host}/_haip/media/${firstAsset}`] : [];
  const siteName = r.live.doc.site.name;
  if (r.v2) {
    const title = r.page.seo.title || `${r.page.title} · ${siteName}`;
    const description = (r.page.seo.description || r.live.doc.site.tagline || "").slice(0, 170);
    return { title, description, alternates: { canonical: `https://${host}${r.page.slug}` },
      ...(r.system && r.page.slug !== "/policies" && !r.blog ? { robots: { index: false } } : {}),
      openGraph: { title, description, siteName, type: "website", locale: "en_IN", images: image } };
  }
  const { page } = r;
  const title = (page.seo.title || page.title).replace(/\{stay\}/gi, r.stay?.name || "");
  const description = (page.seo.description || r.stay?.summary || r.live.doc.site.tagline || "").slice(0, 170);
  return {
    title, description, alternates: { canonical: `https://${host}${page.key === "stay" ? `/stays/${r.slug}` : page.path}` },
    openGraph: { title, description, siteName, type: "website", locale: "en_IN", images: image },
  };
}

export default async function SitePage({ params, searchParams }: { params: Promise<Params>; searchParams: Promise<Search> }) {
  const { host, path } = await params;
  const r = await resolve(host, path);
  if (!r) notFound();
  const env = envFor(r.live, { mode: "live", base: "", query: queryOf(await searchParams), stay: r.stay, mediaBase: "/_haip/media" });
  const p = "/" + (path || []).join("/");
  const sys = r.v2 && r.blog ? { main: r.blog.article ? <ArticleView a={r.blog.article} env={env} /> : <BlogList items={r.blog.items || []} env={env} /> }
    : r.v2 && r.system ? systemPage(r.live, r.page.slug, env) : null;
  if (r.v2 && r.system && !sys) notFound();
  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd(r, host)).replace(/</g, "\u003c") }} />
      {r.v2 ? <SiteRendererV2 live={r.live} page={r.page} env={env} main={sys?.main} /> : <><V1Fonts /><SiteRenderer live={r.live} page={r.page} env={env} /></>}
      <PageView path={p} />
      <Consent pixel={r.live.tracking?.pixel_id} ga4={r.live.tracking?.ga4_id} />
    </>
  );
}
