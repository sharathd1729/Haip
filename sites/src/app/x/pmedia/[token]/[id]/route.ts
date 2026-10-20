// Photos in a draft preview (the draft may use photos the live site doesn't).
import { type NextRequest } from "next/server";
import { apiRoot } from "@/lib/haip";

export async function GET(_req: NextRequest, ctx: { params: Promise<{ token: string; id: string }> }) {
  const { token, id } = await ctx.params;
  if (!/^[0-9a-f-]{36}$/.test(id) || token.length > 400) return new Response("Not found", { status: 404 });
  const r = await fetch(`${apiRoot()}/public/preview/${encodeURIComponent(token)}/media/${id}`, { redirect: "manual", cache: "no-store" }).catch(() => null);
  const loc = r?.headers.get("location");
  if (!r || r.status !== 302 || !loc || !loc.startsWith("https://")) return new Response("Not found", { status: 404 });
  return new Response(null, { status: 302, headers: { location: loc, "cache-control": "private, max-age=600" } });
}
