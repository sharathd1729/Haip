import { type NextRequest } from "next/server";
import { getBlog, getLive, siteHost } from "@/lib/haip";
import { languagesOf } from "@/site-blocks/v2/i18n";
import { isV2 } from "@/site-blocks/v2/types";

const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;");

export async function GET(req: NextRequest) {
  const host = siteHost(req.headers.get("x-forwarded-host") || req.headers.get("host"));
  const live = host ? await getLive(host).catch(() => null) : null;
  if (!live) return new Response("Not found", { status: 404 });
  const paths: string[] = [];
  if (isV2(live)) {
    const stays = live.stays_index || [];
    const base = [...live.doc.pages.map(p => p.slug), ...(stays.length > 1 ? ["/compare"] : []),
      ...stays.filter(s => s.slug).map(s => `/stays/${s.slug}`)];
    paths.push(...base);
    for (const l of languagesOf(live)) paths.push(...base.map(p => `/${l}${p === "/" ? "" : p}`));   // website phase 6
    const blog = (await getBlog(host).catch(() => null)) as { items?: { slug: string }[] } | null;
    if (blog?.items?.length) paths.push("/blog", ...blog.items.map(i => `/blog/${i.slug}`));
  }
  else {
    paths.push(...live.doc.pages.filter(p => !["stay", "book", "manage"].includes(p.key)).map(p => p.path));
    if (live.doc.pages.some(p => p.key === "stay")) paths.push(...live.stays.map(s => `/stays/${s.slug}`));
  }
  const urls = paths.map(p => `  <url><loc>${esc(`https://${host}${p}`)}</loc></url>`).join("\n");
  const xml = `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls}\n</urlset>\n`;
  return new Response(xml, { headers: { "content-type": "application/xml", "cache-control": "public, max-age=3600" } });
}
