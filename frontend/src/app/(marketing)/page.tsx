import type { Metadata } from "next";
import { HeroSection } from "@/components/marketing/homepage/HeroSection";
import { ProblemSolutionSection } from "@/components/marketing/homepage/ProblemSolutionSection";
import { PlatformOverviewSection } from "@/components/marketing/homepage/PlatformOverviewSection";
import { ProductShowcaseSection } from "@/components/marketing/homepage/ProductShowcaseSection";
import { UnifiedInboxSection } from "@/components/marketing/homepage/UnifiedInboxSection";
import { CrmSection } from "@/components/marketing/homepage/CrmSection";
import { AutomationSection } from "@/components/marketing/homepage/AutomationSection";
import { AnalyticsSection } from "@/components/marketing/homepage/AnalyticsSection";
import { OutcomesSection } from "@/components/marketing/homepage/OutcomesSection";
import { IntegrationsSection } from "@/components/marketing/homepage/IntegrationsSection";
import { PricingSection } from "@/components/marketing/homepage/PricingSection";
import { FaqSection } from "@/components/marketing/homepage/FaqSection";
import { FinalCtaSection } from "@/components/marketing/homepage/FinalCtaSection";

export const metadata: Metadata = {
  title: "HAIP — The Hospitality CRM for Hotels, Resorts & Vacation Rentals",
  description:
    "Manage WhatsApp, Instagram, OTA conversations, Voice AI, bookings, guest relationships and automations from one unified hospitality platform.",
};

export default function HomePage() {
  return (
    <div className="haip-home">
      <HeroSection />
      <ProblemSolutionSection />
      <PlatformOverviewSection />
      <ProductShowcaseSection />
      <UnifiedInboxSection />
      <CrmSection />
      <AutomationSection />
      <AnalyticsSection />
      <OutcomesSection />
      <IntegrationsSection />
      <PricingSection />
      <FaqSection />
      <FinalCtaSection />
    </div>
  );
}
