import { BookOpen } from "@/lib/icons";
import { ComingSoon } from "@/components/marketing/ComingSoon";

export default function BlogPage() {
  return (
    <ComingSoon
      eyebrow="Blog · coming soon"
      title="Hospitality intelligence, written by operators"
      description="We're putting together long-form pieces on AI in hospitality, WhatsApp playbooks, call QA rubrics, and lessons from working with luxury villa and travel operators. First articles drop this quarter."
      icon={<BookOpen size={12} />}
      accent="teal"
      primaryCta={{ label: "Get notified", href: "/contact?topic=blog" }}
      secondaryCta={{ label: "See case studies", href: "/case-studies" }}
      highlights={[
        { title: "Auto-QA for hospitality calls", desc: "The 12-point rubric we use across villa, hotel and DMC clients." },
        { title: "WhatsApp Business setup, end-to-end", desc: "Meta embedded signup, template approvals, opt-in playbooks." },
        { title: "Indian-English transcription tips", desc: "Whisper vs Deepgram on hospitality calls — accuracy benchmarks." },
        { title: "The DPDP playbook for hotel ops", desc: "Consent, residency, deletion workflows in plain English." },
      ]}
    />
  );
}

export const metadata = { title: "HAIP Blog — Hospitality intelligence" };
