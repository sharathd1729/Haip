// /_haip/media/<asset id>: HAIP checks the photo belongs to this site's live version and answers with a short-lived
// signed storage URL; the browser follows the redirect.
import { type NextRequest } from "next/server";
import { apiRoot, siteHost, isStorageRedirect } from "@/lib/haip";

export async function GET(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const host = siteHost(req.headers.get("x-forwarded-host") || req.headers.get("host"));
  if (!host || !/^[0-9a-f-]{36}$/.test(id)) return new Response("Not found", { status: 404 });
  const r = await fetch(`${apiRoot()}/public/sites/${encodeURIComponent(host)}/media/${id}`, { redirect: "manual", cache: "no-store" }).catch(() => null);
  const loc = r?.headers.get("location");
  if (!r || r.status !== 302 || !isStorageRedirect(loc)) return new Response("Not found", { status: 404 });
  return new Response(null, { status: 302, headers: { location: loc, "cache-control": "public, max-age=1800" } });
}
