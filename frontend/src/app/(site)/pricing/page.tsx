import SiteHeader from "@/components/site/SiteHeader";
import PricingBody from "@/components/site/PricingBody";
import Cta from "@/components/site/Cta";
import SiteFooter from "@/components/site/SiteFooter";
import JsonLd from "@/components/site/JsonLd";
import { KEYWORDS, faqLd, pageMetadata, softwareLd } from "@/lib/seo";
import "./pricing.css";

// Same questions as the FAQ on the page (PricingBody); search engines read them from here.
const FAQ = [
  ["Is there a free trial?", "Yes. 14 days free, no credit card needed. We set up your account with you and walk you through it."],
  ["Can I change plans later?", "Yes. Move up or down at any time. The new price starts from your next bill."],
  ["Is GST included?", "Prices do not include GST. 18% GST is added to your bill."],
  ["How much do I save yearly?", "Pay for the year and save 20%. You can switch to yearly from your billing settings."],
  ["Is there a lock-in?", "No. Plans are month to month. Cancel any time."],
  ["I have more properties. What do I pay?", "Scale covers several properties. For larger groups, talk to us and we will price it for your setup."],
] as const;

export const metadata = pageMetadata({
  title: "Pricing: simple plans from ₹3,999 a month | HAIP",
  description:
    "HAIP plans for villas, resorts, homestays, hotels and caravans in India. Starter ₹3,999, Growth ₹6,999, Scale ₹9,999 a month. 14-day free trial, no card, cancel any time.",
  path: "/pricing",
  keywords: [...KEYWORDS.pricing],
});

export default function PricingPage() {
  return (
    <>
      <JsonLd data={softwareLd} />
      <JsonLd data={faqLd(FAQ)} />
      <SiteHeader />
      <main>
        <PricingBody />
        <Cta />
      </main>
      <SiteFooter />
    </>
  );
}
