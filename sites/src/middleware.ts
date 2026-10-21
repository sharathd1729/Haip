// Every hostname is a client website. Public paths are rewritten to /s/<host>/<path>; HAIP's own endpoints live under
// /_haip/* (rewritten to /x/*). Direct requests to /s or /x are rewritten like any other path, so they never leak.
import { NextResponse, type NextRequest } from "next/server";
import { siteHost } from "@/lib/haip";

export function middleware(req: NextRequest) {
  const url = req.nextUrl.clone();
  const host = siteHost(req.headers.get("x-forwarded-host") || req.headers.get("host"));
  if (!host) return new NextResponse("Unknown site", { status: 400 });
  const path = url.pathname;
  if (path === "/robots.txt") url.pathname = "/x/robots";
  else if (path === "/sitemap.xml") url.pathname = "/x/sitemap";
  else if (path.startsWith("/_haip/")) url.pathname = "/x/" + path.slice("/_haip/".length);
  else url.pathname = `/s/${host}${path === "/" ? "" : path}`;
  const res = NextResponse.rewrite(url);
  res.headers.set("x-haip-site", host);
  return res;
}

export const config = { matcher: ["/((?!_next/|favicon.ico).*)"] };
