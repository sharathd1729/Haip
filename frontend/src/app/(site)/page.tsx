import SiteHeader from "@/components/site/SiteHeader";
import Hero from "@/components/site/Hero";
import Channels from "@/components/site/Channels";
import Journey from "@/components/site/Journey";
import StayOps from "@/components/site/StayOps";
import Control from "@/components/site/Control";
import Modules from "@/components/site/Modules";
import Ads from "@/components/site/Ads";
import Stays from "@/components/site/Stays";
import Grow from "@/components/site/Grow";
import Cta from "@/components/site/Cta";
import SiteFooter from "@/components/site/SiteFooter";

import JsonLd from "@/components/site/JsonLd";
import { KEYWORDS, organizationLd, pageMetadata, softwareLd } from "@/lib/seo";

export const metadata = pageMetadata({
  title: "HAIP: WhatsApp, calls and bookings for Indian hospitality",
  description:
    "No guest left on read. HAIP answers your guests on WhatsApp and Instagram, records every call, and runs bookings, payments and the stay for villas, resorts, homestays, hotels and caravans in India.",
  path: "/",
  keywords: [...KEYWORDS.home],
});

// New homepage, section order as approved in the mockup (v47).
export default function SiteHome() {
  return (
    <>
      <JsonLd data={organizationLd} />
      <JsonLd data={softwareLd} />
      <SiteHeader />
      <main>
        <Hero />
        <Channels />
        <Journey />
        <StayOps />
        <Control />
        <Modules />
        <Ads />
        <Stays />
        <Grow />
        <Cta />
      </main>
      <SiteFooter />
    </>
  );
}
