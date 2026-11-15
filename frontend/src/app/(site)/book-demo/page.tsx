import SiteHeader from "@/components/site/SiteHeader";
import SiteFooter from "@/components/site/SiteFooter";
import DemoForm from "@/components/site/DemoForm";
import JsonLd from "@/components/site/JsonLd";
import { ArchMark, WhatsAppLine } from "@/components/site/leadParts";
import { breadcrumbLd, pageMetadata } from "@/lib/seo";
import "@/components/site/leadform.css";

export const metadata = pageMetadata({
  title: "Book a demo of HAIP | WhatsApp, calls and bookings for your stay",
  description:
    "A free 30-minute demo on your own WhatsApp: see HAIP answer guests, check calls, take bookings and run the stay for your villa, resort, homestay, hotel or caravans.",
  path: "/book-demo",
  keywords: ["HAIP demo", "hotel CRM demo", "WhatsApp booking software demo", "villa management software India"],
});

const STEPS: [string, string][] = [
  ["You fill this in", "One minute. Nothing to install."],
  ["We WhatsApp you", "Three times to pick from, within 2 working hours."],
  ["30 minutes, live", "Your inbox, a real call, bookings and the stay, on your own data."],
];

export default function BookDemoPage() {
  return (
    <>
      <JsonLd data={breadcrumbLd([["Home", "/"], ["Book a demo", "/book-demo"]])} />
      <SiteHeader />
      <main>
        <section className="lpX bdX gut" aria-labelledby="bdh">
          <ArchMark />
          <div className="wrap">
            <div className="lpg">
              <div className="bdL">
                <span className="lpc"><i aria-hidden="true" />Free 30-minute demo</span>
                <h1 id="bdh">
                  See HAIP on your <em>own guests.</em>
                </h1>
                <p className="lpl">We open your WhatsApp, a real call and your calendar, and show you what HAIP does with them. No slides.</p>
                <ol className="bdn" aria-label="What happens next">
                  {STEPS.map(([t, d], k) => (
                    <li key={t}>
                      <span className="bdi" aria-hidden="true">0{k + 1}</span>
                      <span>
                        <b>{t}</b>
                        <span className="bdd">{d}</span>
                      </span>
                    </li>
                  ))}
                </ol>
                <WhatsAppLine />
              </div>
              <DemoForm />
            </div>
          </div>
        </section>
      </main>
      <SiteFooter />
    </>
  );
}
