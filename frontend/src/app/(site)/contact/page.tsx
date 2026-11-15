import SiteHeader from "@/components/site/SiteHeader";
import SiteFooter from "@/components/site/SiteFooter";
import ContactBody from "@/components/site/ContactBody";
import JsonLd from "@/components/site/JsonLd";
import { breadcrumbLd, pageMetadata } from "@/lib/seo";
import "@/components/site/leadform.css";

export const metadata = pageMetadata({
  title: "Contact HAIP | WhatsApp, email or book a demo",
  description:
    "Talk to a person at HAIP: WhatsApp +91 81476 98153, email info@genhaip.com, or send us a message. Most replies within 2 working hours.",
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
