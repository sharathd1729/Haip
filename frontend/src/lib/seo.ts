import type { Metadata } from "next";

/**
 * Marketing-site SEO in one place: the canonical host, per-page titles/descriptions/keywords, and the JSON-LD the pages
 * embed. Titles and descriptions carry the search terms people use; the `keywords` meta tag is kept for other engines
 * (Google ignores it), so the words that matter must also appear in the page's H1 and copy.
 */
export const SITE_URL = (process.env.NEXT_PUBLIC_SITE_URL || "https://www.genhaip.com").replace(/\/$/, "");
export const SITE_NAME = "HAIP";

type PageSeo = { title: string; description: string; path: string; keywords?: string[]; noindex?: boolean };

export function pageMetadata({ title, description, path, keywords, noindex }: PageSeo): Metadata {
  const url = SITE_URL + path;
  return {
    metadataBase: new URL(SITE_URL),
    title,
    description,
    keywords,
    alternates: { canonical: path },
    openGraph: { type: "website", siteName: SITE_NAME, locale: "en_IN", url, title, description },
    twitter: { card: "summary_large_image", title, description },
    robots: noindex ? { index: false, follow: false } : { index: true, follow: true },
  };
}

/** Search terms per page. Indian-English phrasing, the way owners and managers search. Check them against Search Console. */
export const KEYWORDS = {
  home: [
    "hospitality CRM India",
    "WhatsApp CRM for hotels",
    "AI front desk for hotels",
    "WhatsApp automation for resorts",
    "Instagram DM automation for hotels",
    "hotel call tracking software",
    "villa booking management software",
    "homestay management software India",
  ],
  features: [
    "hotel inbox software",
    "WhatsApp and Instagram inbox for hotels",
    "hotel call recording and scoring",
    "hotel leads pipeline",
    "booking and payment links for hotels",
    "hotel operations software",
    "hotel website builder",
    "hotel marketing automation",
  ],
  pricing: ["hotel CRM pricing India", "WhatsApp CRM pricing", "hospitality software price India", "villa management software price"],
  villas: ["villa management software", "villa booking software India", "WhatsApp booking for villas", "villa caretaker app", "Airbnb villa calendar sync"],
  resorts: ["resort CRM software", "resort booking software India", "wedding and group booking management", "resort WhatsApp automation"],
  hotels: ["hotel CRM India", "travel agent rates software", "missed call follow up for hotels", "hotel front desk software"],
  caravans: ["caravan rental booking software", "campervan booking system India", "fleet booking software for caravans", "caravan trip management"],
} as const;

export type SolutionKey = "villas" | "resorts" | "hotels" | "caravans";

export const organizationLd = {
  "@context": "https://schema.org",
  "@type": "Organization",
  name: SITE_NAME,
  url: SITE_URL,
  logo: SITE_URL + "/logo-wordmark.png",
  areaServed: "IN",
};

export const softwareLd = {
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  name: SITE_NAME,
  applicationCategory: "BusinessApplication",
  operatingSystem: "Web, Android",
  description:
    "HAIP answers guests on WhatsApp and Instagram, records and scores calls, and runs bookings, payments and operations for villas, resorts, homestays, hotels and caravans in India.",
  offers: { "@type": "AggregateOffer", priceCurrency: "INR", lowPrice: "3999", highPrice: "15000", offerCount: "4" },
  url: SITE_URL,
};

export function faqLd(items: ReadonlyArray<readonly [string, string]>) {
  return {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: items.map(([q, a]) => ({ "@type": "Question", name: q, acceptedAnswer: { "@type": "Answer", text: a } })),
  };
}

export function breadcrumbLd(trail: ReadonlyArray<readonly [string, string]>) {
  return {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: trail.map(([name, path], i) => ({ "@type": "ListItem", position: i + 1, name, item: SITE_URL + path })),
  };
}
