import { BookOpen } from "lucide-react";
import { ComingSoon } from "@/components/marketing/ComingSoon";

export default function DocsPage() {
  return (
    <ComingSoon
      eyebrow="Documentation"
      title="Setup guides, integration walkthroughs &amp; API reference"
      description="The full HAIP documentation hub — setup checklists for WhatsApp Cloud API, CallerDesk / Acefone, Hostaway, and step-by-step guides for every role. We're polishing the public site; in the meantime your account manager has the full doc set."
      icon={<BookOpen size={12} />}
      accent="cyan"
      primaryCta={{ label: "Talk to your account manager", href: "/contact?topic=support" }}
      secondaryCta={{ label: "API reference (coming)", href: "/api-docs" }}
      highlights={[
        { title: "WhatsApp Embedded Signup", desc: "Meta verification, number provisioning, template setup — 15-min walkthrough." },
        { title: "CallerDesk + Acefone setup", desc: "IVR flow, recording consent, webhook config, click-to-call API keys." },
        { title: "Role &amp; permission model", desc: "All 11 roles, attribute-based scoping per property / department." },
        { title: "Hostaway sync", desc: "Two-way bookings + guests + inquiry import." },
      ]}
    />
  );
}

export const metadata = { title: "HAIP Documentation — Setup &amp; integration guides" };
