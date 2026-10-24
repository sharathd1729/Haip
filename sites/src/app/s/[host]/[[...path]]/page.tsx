// A page of a live client site. Data is cached for 5 minutes and refreshed at once when HAIP publishes (revalidate).
// A published version is either a v1 block document (SiteRenderer) or a v2 SiteSpec (SiteRendererV2); isV2 picks.
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { PageView } from "@/components/PageView";
import { type AnyLive, envFor, getLive, getStay, queryOf } from "@/lib/haip";
import { findPage, SiteRenderer } from "@/site-blocks/SiteRenderer";
import type { LiveData, Page, Stay } from "@/site-blocks/types";
import { SiteRendererV2 } from "@/site-blocks/v2/SiteRendererV2";
import { findPageV2, isV2, type LiveDataV2, type PageV2 } from "@/site-blocks/v2/types";

type Params = { host: string; path?: string[] };
type Search = Record<string, string | string[] | undefined>;
type Found =
  | { v2: false; live: LiveData; page: Page; slug?: string; stay: Stay | null }
  | { v2: true; live: LiveDataV2; page: PageV2; stay: null };

async function resolve(host: string, path: string[] | undefined): Promise<Found | null> {
  const live: AnyLive | null = await getLive(host);
  if (!live) return null;
  const p = "/" + (path || []).join("/");
  if (isV2(live)) {
    const page = findPageV2(live, p);
    return page ? { v2: true, live, page, stay: null } : null;
  }
  const found = findPage(live, p);
  if (!found) return null;
  const stay = found.slug ? await getStay(host, found.slug) : null;
  return { v2: false, live, page: found.page, slug: found.slug, stay };
}

function jsonLd(r: Found, host: string) {
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
  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd(r, host)).replace(/</g, "<") }} />
      {r.v2 ? <SiteRendererV2 live={r.live} page={r.page} env={env} /> : <SiteRenderer live={r.live} page={r.page} env={env} />}
      <PageView path={p} />
    </>
  );
}
