import type { Metadata, Viewport } from "next";
import { Anton, JetBrains_Mono } from "next/font/google";
import "./site.css";

// The marketing site: "/", /features, /pricing, /solutions/*. Has its own header and footer, so it sits outside (marketing).
// site.css is global by Next's rules, so every selector in it is scoped under .site and its keyframes are prefixed s-.
const display = Anton({
  subsets: ["latin"],
  weight: "400",
  variable: "--font-site-display",
  display: "swap",
});
// Body text reuses the root layout's Onest (--font-onest, variable weight). Loading Onest again here with a weight
// list broke the Turbopack production build ("next/font/google queries have exactly one entry").
const mono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-site-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "HAIP: no guest left on read",
  description:
    "HAIP answers your guests on WhatsApp and Instagram, records every call, and runs bookings, payments and the stay for villas, resorts, homestays, hotels and caravans in India.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#FFFFFF",
  colorScheme: "light",
  viewportFit: "cover",
};

export default function SiteLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div
      className={`site ${display.variable} ${mono.variable}`}
    >
      {children}
    </div>
  );
}
