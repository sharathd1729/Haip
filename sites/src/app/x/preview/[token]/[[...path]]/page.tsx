// A signed preview of a draft (link from the HAIP editor, valid 24 hours). Never cached, never indexed, forms off.
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { envFor, getPreview, getStay, queryOf } from "@/lib/haip";
import { findPage, SiteRenderer } from "@/site-blocks/SiteRenderer";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { robots: { index: false, follow: false }, title: "Preview" };

type Search = Record<string, string | string[] | undefined>;

export default async function Preview({ params, searchParams }: { params: Promise<{ token: string; path?: string[] }>; searchParams: Promise<Search> }) {
  const { token, path } = await params;
  const live = await getPreview(token);
  if (!live) notFound();
  const found = findPage(live, "/" + (path || []).join("/"));
  if (!found) notFound();
  const stay = found.slug ? await getStay("", found.slug, token) : null;
  const env = envFor(live, { mode: "preview", base: `/_haip/preview/${token}`, query: queryOf(await searchParams), stay,
    mediaBase: `/_haip/pmedia/${token}` });
  const banner = <div className="k-preview-bar">Preview of draft version {live.version.number}. Forms and booking are switched off.</div>;
  return <SiteRenderer live={live} page={found.page} env={env} banner={banner} />;
}
