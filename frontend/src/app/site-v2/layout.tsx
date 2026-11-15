import type { Metadata, Viewport } from "next";
import { Anton, JetBrains_Mono, Onest } from "next/font/google";
import "./site.css";

// Preview route for the new marketing site (approved mockup, ported). Not indexed until it replaces "/".
// site.css is global by Next's rules, so every selector in it is scoped under .site and its keyframes are prefixed s-.
const display = Anton({
  subsets: ["latin"],
  weight: "400",
  variable: "--font-site-display",
  display: "swap",
});
const body = Onest({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-site-body",
  display: "swap",
});
const mono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["500", "600"],
  variable: "--font-site-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "HAIP: no guest left on read",
  description:
    "HAIP answers your guests on WhatsApp and Instagram, records every call, and runs bookings, payments and the stay for villas, resorts, homestays, hotels and caravans in India.",
  robots: { index: false, follow: false },
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
      className={`site ${display.variable} ${body.variable} ${mono.variable}`}
    >
      {children}
    </div>
  );
}
