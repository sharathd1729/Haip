// A signed preview of a draft (link from the HAIP editor, valid 24 hours). Never cached, never indexed, forms off.
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { envFor, getPreview, getStay, queryOf } from "@/lib/haip";
import { findPage, SiteRenderer } from "@/site-blocks/SiteRenderer";
import { SiteRendererV2 } from "@/site-blocks/v2/SiteRendererV2";
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
    const page = findPageV2(live, "/" + (path || []).join("/"));
    if (!page) notFound();
    const env = envFor(live, { mode: "preview", base, query: queryOf(await searchParams), mediaBase: `/_haip/pmedia/${token}` });
    return <SiteRendererV2 live={live} page={page} env={env} banner={banner} />;
  }
  const found = findPage(live, "/" + (path || []).join("/"));
  if (!found) notFound();
  const stay = found.slug ? await getStay("", found.slug, token) : null;
  const env = envFor(live, { mode: "preview", base, query: queryOf(await searchParams), stay,
    mediaBase: `/_haip/pmedia/${token}` });
  return <SiteRenderer live={live} page={found.page} env={env} banner={banner} />;
}
