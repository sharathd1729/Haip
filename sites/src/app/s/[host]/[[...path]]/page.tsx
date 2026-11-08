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
import { ComparePage, StayPage } from "@/site-blocks/v2/stay";
import { LANGS, languagesOf, localise } from "@/site-blocks/v2/i18n";
import { findPage, SiteRenderer } from "@/site-blocks/SiteRenderer";
import type { LiveData, Page, Stay } from "@/site-blocks/types";
import { SiteRendererV2, systemPage } from "@/site-blocks/v2/SiteRendererV2";
import { findPageV2, isV2, SYSTEM_PAGES, type LiveDataV2, type PageV2 } from "@/site-blocks/v2/types";

type Params = { host: string; path?: string[] };
type Search = Record<string, string | string[] | undefined>;
type Found =
  | { v2: false; live: LiveData; page: Page; slug?: string; stay: Stay | null }
  | { v2: true; live: LiveDataV2; page: PageV2; stay: null; system?: boolean; blog?: { items?: BlogItem[]; article?: Article };
      stayPage?: Stay; compare?: boolean; lang?: string; path?: string };

async function resolve(host: string, path: string[] | undefined): Promise<Found | null> {
  const found = await resolveIn(host, path);
  return found && found.v2 ? { ...found, path: "/" + (path || []).join("/") } : found;
}

/** /hi/<page> = the same page with its Hindi words (website phase 6), only when the live version has them. */
async function resolveIn(host: string, path: string[] | undefined): Promise<Found | null> {
  const raw: AnyLive | null = await getLive(host);
  if (!raw) return null;
  const lang = isV2(raw) && path?.[0] && languagesOf(raw).includes(path[0]) ? path[0] : undefined;
  const live: AnyLive = lang && isV2(raw) ? localise(raw, lang) : raw;
  const p = "/" + (lang ? path!.slice(1) : path || []).join("/");
  if (isV2(live) && lang) {
    const r = await resolveV2(host, live, p);
    return r && r.v2 ? { ...r, lang } : r;
  }
  if (isV2(live)) return resolveV2(host, live, p);
  return resolveV1(host, live, p);
}

async function resolveV2(host: string, live: LiveDataV2, p: string): Promise<Found | null> {
  const page = findPageV2(live, p);
  if (page) return { v2: true, live, page, stay: null };
  const low = p.toLowerCase();
  const sys = (title: string, description: string) => ({ slug: low, title, nav: false, sections: [],
    seo: { title: `${title} · ${live.doc.site.name}`.slice(0, 70), description: description.slice(0, 160) } });
  if (low === "/compare" && (live.stays_index || []).length > 1) {           // multi-property (website phase 6)
    return { v2: true, live, stay: null, system: true, compare: true,
      page: sys("Compare stays", `Every stay at ${live.doc.site.name} side by side: guests, bedrooms and what's included.`) };
  }
  if (low.startsWith("/stays/") && low.split("/").length === 3) {
    const st = await getStay(host, low.slice(7));
    if (!st) return null;
    return { v2: true, live, stay: null, system: true, stayPage: st, page: sys(st.name, st.summary || live.doc.site.tagline || st.name) };
  }
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

async function resolveV1(host: string, live: LiveData, p: string): Promise<Found | null> {
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
    const langs = languagesOf(r.live);
    const bare = r.lang ? (r.path || "/").replace(new RegExp(`^/${r.lang}(?=/|$)`), "") || "/" : r.path || r.page.slug;
    const languages = langs.length ? Object.fromEntries([["en-IN", `https://${host}${bare}`], ["x-default", `https://${host}${bare}`],
      ...langs.map(l => [LANGS[l].hreflang, `https://${host}/${l}${bare === "/" ? "" : bare}`])]) : undefined;
    return { title, description, alternates: { canonical: `https://${host}${r.path || r.page.slug}`, languages },
      ...(r.system && r.page.slug !== "/policies" && !r.blog && !r.stayPage && !r.compare ? { robots: { index: false } } : {}),
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
  const p = "/" + (path || []).join("/");
  const lang = r.v2 ? r.lang : undefined;
  const env = envFor(r.live, { mode: "live", base: lang ? `/${lang}` : "", query: queryOf(await searchParams), stay: r.stay, mediaBase: "/_haip/media" });
  // a language switch at the top of a translated site (website phase 6)
  const other = r.v2 ? languagesOf(r.live) : [];
  const bare = lang ? p.replace(new RegExp(`^/${lang}(?=/|$)`), "") || "/" : p;
  const switcher = other.length ? <p className="sv-wrap sv-langbar">{lang
    ? <a href={bare} hrefLang="en-IN" lang="en">English</a>
    : other.map(l => <a key={l} href={`/${l}${bare === "/" ? "" : bare}`} hrefLang={LANGS[l].hreflang} lang={l}>{LANGS[l].switchTo}</a>)}</p> : null;
  const sys = r.v2 && r.stayPage ? { main: <StayPage stay={r.stayPage} item={(r.live.stays_index || []).find(i => i.id === r.stayPage!.id)} live={r.live} env={env} /> }
    : r.v2 && r.compare ? { main: <ComparePage live={r.live} env={env} /> }
    : r.v2 && r.blog ? { main: r.blog.article ? <ArticleView a={r.blog.article} env={env} /> : <BlogList items={r.blog.items || []} env={env} /> }
    : r.v2 && r.system ? systemPage(r.live, r.page.slug, env) : null;
  if (r.v2 && r.system && !sys) notFound();
  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd(r, host)).replace(/</g, "\u003c") }} />
      {r.v2 ? <div lang={lang || undefined}><SiteRendererV2 live={r.live} page={r.page} env={env} main={sys?.main} banner={switcher} /></div>
        : <><V1Fonts /><SiteRenderer live={r.live} page={r.page} env={env} /></>}
      <PageView path={p} />
      <Consent pixel={r.live.tracking?.pixel_id} ga4={r.live.tracking?.ga4_id} gads={r.live.tracking?.gads} />
    </>
  );
}
