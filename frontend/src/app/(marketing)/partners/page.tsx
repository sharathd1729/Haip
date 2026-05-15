import { Handshake } from "lucide-react";
import { ComingSoon } from "@/components/marketing/ComingSoon";

export default function PartnersPage() {
  return (
    <ComingSoon
      eyebrow="Partner programme"
      title="Build with us · sell with us · refer with us"
      description="HAIP partners with hospitality consultants, PMS vendors, telephony providers, and digital agencies who serve villas, hotels, resorts and DMCs across India. Three tracks: Reseller, Integration, Referral."
      icon={<Handshake size={12} />}
      accent="amber"
      primaryCta={{ label: "Apply to partner", href: "/contact?topic=partnerships" }}
      secondaryCta={{ label: "Email partnerships team", href: "mailto:partnerships@haip.app" }}
      highlights={[
        { title: "Reseller partners", desc: "Hospitality consultants who want to onboard HAIP for their clients. Margin share + co-marketing." },
        { title: "Integration partners", desc: "PMS, channel manager, OTA, payment platforms. Listed on /integrations + revenue share on jointly-acquired tenants." },
        { title: "Referral partners", desc: "Hospitality advisors and individual operators. Flat referral fee on the first 12 months of any closed deal." },
        { title: "Agency partners", desc: "Digital agencies running performance marketing for hospitality brands. We pair HAIP onboarding with their funnels." },
      ]}
    />
  );
}

export const metadata = { title: "HAIP Partner Programme — Reseller, Integration, Referral" };
