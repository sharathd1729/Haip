import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/seo";
import { fetchCaseStudies } from "@/lib/caseStudies";

// Every public marketing page. Keep in step with src/app/(marketing): a page missing here is still found, just slower.
const PAGES: Array<[path: string, priority: number, freq: MetadataRoute.Sitemap[number]["changeFrequency"]]> = [
  ["/", 1, "weekly"],
  ["/features", 0.9, "monthly"],
  ["/pricing", 0.9, "monthly"],
  ["/solutions/villas", 0.8, "monthly"],
  ["/solutions/resorts", 0.8, "monthly"],
  ["/solutions/hotels", 0.8, "monthly"],
  ["/solutions/travel", 0.8, "monthly"],
  ["/book-demo", 0.8, "yearly"],
  ["/integrations", 0.6, "monthly"],
  ["/case-studies", 0.6, "weekly"],
  ["/contact", 0.5, "yearly"],
  ["/security", 0.4, "yearly"],
  ["/trust", 0.4, "yearly"],
  ["/dpdp", 0.3, "yearly"],
  ["/roadmap", 0.3, "monthly"],
  ["/status", 0.2, "daily"],
  ["/privacy", 0.2, "yearly"],
  ["/terms", 0.2, "yearly"],
];

export const revalidate = 3600;

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const now = new Date();
  const pages: MetadataRoute.Sitemap = PAGES.map(([path, priority, changeFrequency]) => ({
    url: SITE_URL + path,
    lastModified: now,
    changeFrequency,
    priority,
  }));
  // Published case studies come from the API; if it is down the sitemap still serves the static pages.
  let studies: MetadataRoute.Sitemap = [];
  try {
    studies = (await fetchCaseStudies()).map((c) => ({
      url: `${SITE_URL}/case-studies/${c.slug}`,
      lastModified: c.published_at ? new Date(c.published_at) : now,
      changeFrequency: "monthly",
      priority: 0.5,
    }));
  } catch {
    studies = [];
  }
  return [...pages, ...studies];
}
