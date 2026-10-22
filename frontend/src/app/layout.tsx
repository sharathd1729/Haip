import type { Metadata, Viewport } from "next";
import { Bricolage_Grotesque, Figtree } from "next/font/google";
import "./globals.css";
import { Providers } from "@/components/providers";
import { PWARegister } from "@/components/PWARegister";
import { UpdateBanner } from "@/components/UpdateBanner";
import { ConnectionBanner } from "@/components/ConnectionBanner";
import { ResumeRevalidator } from "@/components/ResumeRevalidator";

// Hospitality Hybrid type system (docs/DESIGN.md): Figtree for everything people read and operate, Bricolage Grotesque for
// page titles, headline figures and section headings. Both self-hosted by next/font; --font-sans and --font-display in
// globals.css point at these variables, with a system fallback if either fails to load.
const uiFont = Figtree({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700", "800"],
  variable: "--font-figtree",
  display: "swap",
});

const displayFont = Bricolage_Grotesque({
  subsets: ["latin"],
  weight: ["500", "600", "700", "800"],
  variable: "--font-display",
  display: "swap",
});

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#FFFFFF" },
    { media: "(prefers-color-scheme: dark)", color: "#0B1F1B" },
  ],
  viewportFit: "cover",
};

export const metadata: Metadata = {
  title: "HAIP — Hospitality AI Intelligence Platform",
  description: "Unified inbox + AI call intelligence for luxury hospitality",
  manifest: "/manifest.json",
  openGraph: {
    title: "HAIP — Hospitality AI Intelligence Platform",
    description: "Unified inbox + AI call intelligence for luxury hospitality",
    url: "https://www.genhaip.com",
    siteName: "HAIP",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "HAIP — Hospitality AI Intelligence Platform",
    description: "Unified inbox + AI call intelligence for luxury hospitality",
  },
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "HAIP",
  },
  formatDetection: {
    telephone: false,
  },
  // Tabs, bookmarks and home screens use the "A" (teal triangle) from the
  // HAIP wordmark on a white tile -- the full wordmark is unreadable at 16px.
  // src/app/favicon.ico is the same mark.
  icons: {
    icon: [
      { url: "/icon-192.png", type: "image/png", sizes: "192x192" },
      { url: "/icon-512.png", type: "image/png", sizes: "512x512" },
    ],
    apple: { url: "/apple-touch-icon.png", sizes: "180x180" },
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${uiFont.variable} ${displayFont.variable} h-full antialiased`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: `
          try {
            var p = window.location.pathname;
            var isApp = p.startsWith('/dashboard') || p.startsWith('/onboarding') || p.startsWith('/login') || p.startsWith('/register');
            if (isApp) {
              var s = localStorage.getItem('haip_color_scheme');
              var prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
              if (s === 'dark' || (s === null && prefersDark)) {
                document.documentElement.classList.add('dark');
              }
            }
          } catch(e) {}
        `}} />
      </head>
      <body className="min-h-full bg-background font-sans">
        <Providers>{children}</Providers>
        <PWARegister />
        <UpdateBanner />
        <ConnectionBanner />
        <ResumeRevalidator />
      </body>
    </html>
  );
}
