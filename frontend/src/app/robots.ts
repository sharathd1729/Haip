import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/seo";

// Public marketing pages are crawlable; the app, auth flows, private guest links and previews are not.
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        disallow: ["/dashboard", "/api/", "/connect", "/login", "/register", "/forgot-password", "/reset-password", "/r/", "/yaad", "/site-v2", "/design-lab"],
      },
    ],
    sitemap: SITE_URL + "/sitemap.xml",
    host: SITE_URL,
  };
}
