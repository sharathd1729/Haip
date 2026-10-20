// Browser -> HAIP guest API proxy. The site's hostname picks the tenant on HAIP's side; the guest's IP is passed on so
// HAIP's per-IP limits apply to the guest, not to this server. Only the guest API paths below are allowed.
import { type NextRequest } from "next/server";
import { apiRoot, siteHost } from "@/lib/haip";

const ALLOWED = /^(availability|quote|holds|holds\/[0-9a-f-]{36}|enquiries|manage|manage\/lookup|manage\/pay|views|stays\/[a-z0-9-]{1,80})$/;
const MAX_BODY = 16 * 1024;

async function forward(req: NextRequest, path: string[]) {
  const host = siteHost(req.headers.get("x-forwarded-host") || req.headers.get("host"));
  const sub = path.join("/");
  if (!host || !ALLOWED.test(sub)) return Response.json({ detail: { code: "not_found", message: "Not found" } }, { status: 404 });
  const body = req.method === "GET" ? undefined : await req.text();
  if (body && body.length > MAX_BODY) return Response.json({ detail: { code: "too_large", message: "Too large" } }, { status: 413 });
  const ip = (req.headers.get("x-forwarded-for") || "").split(",")[0].trim() || req.headers.get("x-real-ip") || "";
  const r = await fetch(`${apiRoot()}/public/sites/${encodeURIComponent(host)}/${sub}${req.nextUrl.search}`, {
    method: req.method, body, cache: "no-store", redirect: "manual",
    headers: { "content-type": "application/json", ...(ip ? { "x-forwarded-for": ip } : {}),
      "user-agent": (req.headers.get("user-agent") || "").slice(0, 300) },
  }).catch(() => null);
  if (!r) return Response.json({ detail: { code: "unavailable", message: "We couldn't reach the booking system. Try again." } }, { status: 503 });
  return new Response(r.status === 204 ? null : await r.text(),
    { status: r.status, headers: { "content-type": r.headers.get("content-type") || "application/json", "cache-control": "no-store" } });
}

export async function GET(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return forward(req, (await ctx.params).path);
}

export async function POST(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return forward(req, (await ctx.params).path);
}
