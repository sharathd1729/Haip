import { type NextRequest } from "next/server";
import { getLive, siteHost } from "@/lib/haip";

const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;");

export async function GET(req: NextRequest) {
  const host = siteHost(req.headers.get("x-forwarded-host") || req.headers.get("host"));
  const live = host ? await getLive(host).catch(() => null) : null;
  if (!live) return new Response("Not found", { status: 404 });
  const paths = live.doc.pages.filter(p => !["stay", "book", "manage"].includes(p.key)).map(p => p.path);
  if (live.doc.pages.some(p => p.key === "stay")) paths.push(...live.stays.map(s => `/stays/${s.slug}`));
  const urls = paths.map(p => `  <url><loc>${esc(`https://${host}${p}`)}</loc></url>`).join("\n");
  const xml = `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls}\n</urlset>\n`;
  return new Response(xml, { headers: { "content-type": "application/xml", "cache-control": "public, max-age=3600" } });
}
