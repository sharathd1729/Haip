import { type NextRequest } from "next/server";
import { siteHost } from "@/lib/haip";

export function GET(req: NextRequest) {
  const host = siteHost(req.headers.get("x-forwarded-host") || req.headers.get("host"));
  const body = ["User-agent: *", "Allow: /", "Disallow: /_haip/", "Disallow: /book", "Disallow: /my-booking",
    `Sitemap: https://${host}/sitemap.xml`, ""].join("\n");
  return new Response(body, { headers: { "content-type": "text/plain", "cache-control": "public, max-age=3600" } });
}
