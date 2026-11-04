// A signed preview of a draft (link from the HAIP editor, valid 24 hours). Never cached, never indexed, forms off.
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { envFor, getPreview, getStay, queryOf } from "@/lib/haip";
import { V1Fonts } from "@/components/V1Fonts";
import { findPage, SiteRenderer } from "@/site-blocks/SiteRenderer";
import { SiteRendererV2 } from "@/site-blocks/v2/SiteRendererV2";
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
    const page = findPageV2(shown, "/" + (lang ? path!.slice(1) : path || []).join("/"));
    if (!page) notFound();
    const env = envFor(shown, { mode: "preview", base: lang ? `${base}/${lang}` : base, query: queryOf(await searchParams), mediaBase: `/_haip/pmedia/${token}` });
    return <div lang={lang}><SiteRendererV2 live={shown} page={page} env={env} banner={banner} /></div>;
  }
  const found = findPage(live, "/" + (path || []).join("/"));
  if (!found) notFound();
  const stay = found.slug ? await getStay("", found.slug, token) : null;
  const env = envFor(live, { mode: "preview", base, query: queryOf(await searchParams), stay,
    mediaBase: `/_haip/pmedia/${token}` });
  return <><V1Fonts /><SiteRenderer live={live} page={found.page} env={env} banner={banner} /></>;
}
