import { Code2 } from "@/lib/icons";
import { ComingSoon } from "@/components/marketing/ComingSoon";

export default function ApiDocsPage() {
  return (
    <ComingSoon
      eyebrow="API reference · coming soon"
      title="HAIP API — build on top of your guest intelligence"
      description="REST + webhook API for guests, inquiries, conversations, calls, scores and stays. Used internally today, public OpenAPI spec ships with v1.0. Early-access available on the Scale and Enterprise plans."
      icon={<Code2 size={12} />}
      accent="purple"
      primaryCta={{ label: "Request early API access", href: "/contact?topic=api" }}
      secondaryCta={{ label: "See pricing", href: "/pricing" }}
      highlights={[
        { title: "Webhooks", desc: "Subscribe to inquiry.created, call.scored, guest.updated, message.received." },
        { title: "REST endpoints", desc: "Full CRUD on Guests, Inquiries, Conversations, Calls, Stays, Campaigns." },
        { title: "OpenAPI 3.1 spec", desc: "Auto-generated client libraries for JS/TS, Python, Go." },
        { title: "OAuth2 + scoped tokens", desc: "Per-property, per-role access tokens with rotation." },
      ]}
    />
  );
}

export const metadata = { title: "HAIP API Reference — Coming soon" };
