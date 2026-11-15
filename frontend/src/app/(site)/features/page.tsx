import SiteHeader from "@/components/site/SiteHeader";
import FeaturesBody from "@/components/site/FeaturesBody";
import Cta from "@/components/site/Cta";
import SiteFooter from "@/components/site/SiteFooter";
import JsonLd from "@/components/site/JsonLd";
import { KEYWORDS, pageMetadata, softwareLd } from "@/lib/seo";
import "./features.css";

export const metadata = pageMetadata({
  title: "Features: inbox, calls, leads, bookings and operations | HAIP",
  description:
    "Everything HAIP does for your property: one WhatsApp and Instagram inbox, calls recorded and scored, a leads pipeline, bookings and payment links, operations, your website and Instagram posts, and reports.",
  path: "/features",
  keywords: [...KEYWORDS.features],
});

export default function FeaturesPage() {
  return (
    <>
      <JsonLd data={softwareLd} />
      <SiteHeader />
      <main>
        <FeaturesBody />
        <Cta />
      </main>
      <SiteFooter />
    </>
  );
}
