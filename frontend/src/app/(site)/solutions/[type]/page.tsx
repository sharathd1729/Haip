import { notFound } from "next/navigation";
import SiteHeader from "@/components/site/SiteHeader";
import SolutionBody from "@/components/site/SolutionBody";
import Cta from "@/components/site/Cta";
import SiteFooter from "@/components/site/SiteFooter";
import JsonLd from "@/components/site/JsonLd";
import { SOLUTIONS } from "@/components/site/solutions";
import { KEYWORDS, breadcrumbLd, pageMetadata, softwareLd } from "@/lib/seo";
import "./solutions.css";

// URL slugs match the live site so existing links and rankings carry over ("travel" is the caravans page).
const SLUGS = { villas: "villas", resorts: "resorts", hotels: "hotels", travel: "caravans" } as const;
type Slug = keyof typeof SLUGS;

const SEO: Record<Slug, { title: string; description: string }> = {
  villas: {
    title: "Villa management software: WhatsApp, bookings and caretakers | HAIP",
    description:
      "Answer villa guests on WhatsApp and Instagram, take the advance in the chat, hold deposits, keep Airbnb and Booking.com dates in step and send jobs to your caretaker.",
  },
  resorts: {
    title: "Resort CRM and booking software for groups and weddings | HAIP",
    description:
      "One calm desk for busy weekends: every enquiry sorted, wedding and group requests sent to the right person, add-ons sold by link and every call checked.",
  },
  hotels: {
    title: "Hotel CRM for direct bookings, agents and missed calls | HAIP",
    description:
      "Answer travellers and travel agents on WhatsApp, apply agent rates from your rate card, call back every missed call and send quotes, receipts and invoices.",
  },
  travel: {
    title: "Caravan rental booking software: trips, vehicles and crew | HAIP",
    description:
      "Book caravan trips from the first DM, pick the next free vehicle automatically, track papers and service dates, and keep your crew in the loop with a live trip map.",
  },
};

export function generateStaticParams() {
  return Object.keys(SLUGS).map((type) => ({ type }));
}

export async function generateMetadata({ params }: { params: Promise<{ type: string }> }) {
  const { type } = await params;
  if (!(type in SLUGS)) return {};
  const slug = type as Slug;
  return pageMetadata({ ...SEO[slug], path: `/solutions/${slug}`, keywords: [...KEYWORDS[SLUGS[slug]]] });
}

export default async function SolutionPage({ params }: { params: Promise<{ type: string }> }) {
  const { type } = await params;
  if (!(type in SLUGS)) notFound();
  const slug = type as Slug;
  const d = SOLUTIONS[SLUGS[slug]];
  return (
    <>
      <JsonLd data={softwareLd} />
      <JsonLd data={breadcrumbLd([["Home", "/"], [d.label, `/solutions/${slug}`]])} />
      <SiteHeader />
      <main>
        <SolutionBody d={d} />
        <Cta />
      </main>
      <SiteFooter />
    </>
  );
}
