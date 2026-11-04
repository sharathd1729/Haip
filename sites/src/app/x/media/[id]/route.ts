// /_haip/media/<asset id>: HAIP checks the photo belongs to this site's live version and answers with a short-lived
// signed storage URL; the browser follows the redirect.
// /_haip/media/<asset id>?w=640 (website phase 3): the same photo resized here to that width, as AVIF or WebP when the
// browser accepts it (else JPEG), cached by the browser and CDN. The page's srcset lists these widths (v2 Img), so a
// phone downloads a phone-sized photo. sharp ships with Next.js; if it is missing or the photo can't be read, the
// original redirect is the answer, never an error.
import { type NextRequest } from "next/server";
import { apiRoot, siteHost, isStorageRedirect } from "@/lib/haip";

const WIDTHS = new Set([320, 480, 640, 960, 1280, 1920]);
const MAX_BYTES = 25 * 1024 * 1024;

async function resized(loc: string, width: number, accept: string): Promise<Response | null> {
  const sharp = (await import("sharp").catch(() => null))?.default;
  if (!sharp) return null;
  const img = await fetch(loc, { cache: "no-store" }).catch(() => null);
  if (!img || !img.ok || Number(img.headers.get("content-length") || 0) > MAX_BYTES) return null;
  const buf = Buffer.from(await img.arrayBuffer());
  if (buf.length > MAX_BYTES) return null;
  const fmt = accept.includes("image/avif") ? "avif" : accept.includes("image/webp") ? "webp" : "jpeg";
  try {
    let p = sharp(buf, { failOn: "none" }).rotate().resize({ width, withoutEnlargement: true });
    p = fmt === "avif" ? p.avif({ quality: 50 }) : fmt === "webp" ? p.webp({ quality: 72 }) : p.jpeg({ quality: 78, mozjpeg: true });
    const out = await p.toBuffer();
    return new Response(new Uint8Array(out), { headers: { "content-type": `image/${fmt}`, vary: "Accept",
      "cache-control": "public, max-age=86400, s-maxage=604800, stale-while-revalidate=86400" } });
  } catch {
    return null;
  }
}

export async function GET(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const host = siteHost(req.headers.get("x-forwarded-host") || req.headers.get("host"));
  if (!host || !/^[0-9a-f-]{36}$/.test(id)) return new Response("Not found", { status: 404 });
  const r = await fetch(`${apiRoot()}/public/sites/${encodeURIComponent(host)}/media/${id}`, { redirect: "manual", cache: "no-store" }).catch(() => null);
  const loc = r?.headers.get("location");
  if (!r || r.status !== 302 || !isStorageRedirect(loc)) return new Response("Not found", { status: 404 });
  const w = Number(req.nextUrl.searchParams.get("w"));
  if (WIDTHS.has(w)) {
    const out = await resized(loc, w, req.headers.get("accept") || "");
    if (out) return out;
  }
  return new Response(null, { status: 302, headers: { location: loc, "cache-control": "public, max-age=1800" } });
}
