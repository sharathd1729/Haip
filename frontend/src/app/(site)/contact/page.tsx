import SiteHeader from "@/components/site/SiteHeader";
import SiteFooter from "@/components/site/SiteFooter";
import ContactBody from "@/components/site/ContactBody";
import JsonLd from "@/components/site/JsonLd";
import { breadcrumbLd, pageMetadata } from "@/lib/seo";
import "@/components/site/leadform.css";

export const metadata = pageMetadata({
  title: "Contact HAIP | Sales, support and partnerships",
  description:
    "Talk to the HAIP team: sales and demos, customer support for existing customers, and partnerships. WhatsApp +91 81476 98153 or send us a message.",
  path: "/contact",
});

export default function ContactPage() {
  return (
    <>
      <JsonLd data={breadcrumbLd([["Home", "/"], ["Contact", "/contact"]])} />
      <SiteHeader />
      <main>
        <ContactBody />
      </main>
      <SiteFooter />
    </>
  );
}
