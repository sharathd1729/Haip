// A page of a live client site. Data is cached for 5 minutes and refreshed at once when HAIP publishes (revalidate).
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { PageView } from "@/components/PageView";
import { envFor, getLive, getStay, queryOf } from "@/lib/haip";
import { findPage, SiteRenderer } from "@/site-blocks/SiteRenderer";
import type { LiveData, Stay } from "@/site-blocks/types";

type Params = { host: string; path?: string[] };
type Search = Record<string, string | string[] | undefined>;

async function resolve(host: string, path: string[] | undefined) {
  const live = await getLive(host);
  if (!live) return null;
  const found = findPage(live, "/" + (path || []).join("/"));
  if (!found) return { live, found: null, stay: null as Stay | null };
  const stay = found.slug ? await getStay(host, found.slug) : null;
  return { live, found, stay };
}

function jsonLd(live: LiveData, host: string, stay: Stay | null) {
  const c = live.doc.site.contact;
  return {
    "@context": "https://schema.org", "@type": stay ? "HotelRoom" : "LodgingBusiness",
    name: stay ? stay.name : live.doc.site.name, url: `https://${host}`, telephone: c.phone || undefined, email: c.email || undefined,
    address: c.address ? { "@type": "PostalAddress", streetAddress: c.address, addressCountry: "IN" } : undefined,
    ...(stay ? { occupancy: { "@type": "QuantitativeValue", maxValue: stay.sleeps } } : {}),
  };
}

export async function generateMetadata({ params }: { params: Promise<Params> }): Promise<Metadata> {
  const { host, path } = await params;
  const r = await resolve(host, path);
  if (!r?.found) return { title: "Not found" };
  const { page } = r.found;
  const name = r.stay?.name;
  const title = (page.seo.title || page.title).replace(/\{stay\}/gi, name || "");
  const description = (page.seo.description || r.stay?.summary || r.live.doc.site.tagline || "").slice(0, 170);
  const firstAsset = Object.keys(r.live.assets)[0];
  return {
    title, description, alternates: { canonical: `https://${host}${page.key === "stay" ? `/stays/${r.found.slug}` : page.path}` },
    openGraph: { title, description, siteName: r.live.doc.site.name, type: "website", locale: "en_IN",
      images: r.stay?.photos[0] ? [r.stay.photos[0]] : firstAsset ? [`https://${host}/_haip/media/${firstAsset}`] : [] },
  };
}

export default async function SitePage({ params, searchParams }: { params: Promise<Params>; searchParams: Promise<Search> }) {
  const { host, path } = await params;
  const r = await resolve(host, path);
  if (!r?.found) notFound();
  const env = envFor(r.live, { mode: "live", base: "", query: queryOf(await searchParams), stay: r.stay, mediaBase: "/_haip/media" });
  const p = "/" + (path || []).join("/");
  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd(r.live, host, r.stay)).replace(/</g, "\u003c") }} />
      <SiteRenderer live={r.live} page={r.found.page} env={env} />
      <PageView path={p} />
    </>
  );
}
