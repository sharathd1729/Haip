// A signed preview of a draft (link from the HAIP editor, valid 24 hours). Never cached, never indexed, forms off.
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { envFor, getPreview, getStay, queryOf } from "@/lib/haip";
import { V1Fonts } from "@/components/V1Fonts";
import { findPage, SiteRenderer } from "@/site-blocks/SiteRenderer";
import { SiteRendererV2, templatePageV2 } from "@/site-blocks/v2/SiteRendererV2";
import { StayPage } from "@/site-blocks/v2/stay";
import { StaySearch } from "@/site-blocks/v2/search";
import { languagesOf, localise } from "@/site-blocks/v2/i18n";
import { findPageV2, isV2 } from "@/site-blocks/v2/types";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { robots: { index: false, follow: false }, title: "Preview" };

type Search = Record<string, string | string[] | undefined>;

export default async function Preview({ params, searchParams }: { params: Promise<{ token: string; path?: string[] }>; searchParams: Promise<Search> }) {
  const { token, path } = await params;
  const live = await getPreview(token);
  if (!live) notFound();
  const base = `/_haip/preview/${token}`;
  const banner = <div className="k-preview-bar">Preview of draft version {live.version.number}. Forms and booking are switched off.</div>;
  if (isV2(live)) {
    // /hi/... reads the draft's Hindi words (website phase 6) so they can be checked before publishing
    const lang = path?.[0] && languagesOf(live).includes(path[0]) ? path[0] : undefined;
    const shown = lang ? localise(live, lang) : live;
    const p = ("/" + (lang ? path!.slice(1) : path || []).join("/")).toLowerCase();
    let page = findPageV2(shown, p), main = null;
    let stay = null, packageKey: string | null = null;
    if (!page && p.startsWith("/stays/") && p.split("/").length === 3) {         // stay pages, with the draft's design (W4)
      stay = await getStay("", p.slice(7), token);
      if (stay) page = templatePageV2(shown, "stay", stay.name);
      if (stay && !shown.doc.templates?.stay) {
        main = <StayPage stay={stay} item={(shown.stays_index || []).find(i => i.id === stay!.id)} live={shown} env={envFor(shown, { mode: "preview", base, query: {}, mediaBase: `/_haip/pmedia/${token}` })} />;
        page = { ...page!, sections: [] };
      }
    }
    if (!page && p === "/stays" && (shown.stays_index || []).length > 0) {       // Find your stay (W5)
      page = { slug: "/stays", title: "Find your stay", nav: false, seo: { title: "", description: "" }, sections: [] };
      main = <StaySearch live={shown} env={envFor(shown, { mode: "preview", base, query: {}, mediaBase: `/_haip/pmedia/${token}` })} />;
    }
    if (!page && p.startsWith("/packages/") && p.split("/").length === 3) {
      const pk = (shown.packages_index || []).find(x => x.key === p.slice(10));
      if (pk) { page = templatePageV2(shown, "package", pk.name); packageKey = pk.key; }
    }
    if (!page) notFound();
    const env = { ...envFor(shown, { mode: "preview", base: lang ? `${base}/${lang}` : base, query: queryOf(await searchParams), stay, mediaBase: `/_haip/pmedia/${token}` }), packageKey };
    return <div lang={lang}><SiteRendererV2 live={shown} page={page} env={env} banner={banner} main={main} /></div>;
  }
  const found = findPage(live, "/" + (path || []).join("/"));
  if (!found) notFound();
  const stay = found.slug ? await getStay("", found.slug, token) : null;
  const env = envFor(live, { mode: "preview", base, query: queryOf(await searchParams), stay,
    mediaBase: `/_haip/pmedia/${token}` });
  return <><V1Fonts /><SiteRenderer live={live} page={found.page} env={env} banner={banner} /></>;
}
