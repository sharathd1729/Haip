import type { Metadata, Viewport } from "next";
import { Outfit, Inter } from "next/font/google";
import "./globals.css";
import { Providers } from "@/components/providers";
import { PWARegister } from "@/components/PWARegister";

// Display / heading font: Outfit — per HAIP_Prototype.html, which pairs it
// with Inter. Geometric with a tighter, more architectural feel than Manrope
// at the 700–800 weights used for page titles, KPI values and scores.
const displayFont = Outfit({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700", "800"],
  variable: "--font-display",
  display: "swap",
});

// Body / UI font: Inter — industry-standard, maximal legibility at all sizes
const sansFont = Inter({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
  variable: "--font-sans",
  display: "swap",
});

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  themeColor: "#041C1A",
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
  icons: {
    icon: "/logo.png",
    apple: "/logo.png",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="h-full antialiased" suppressHydrationWarning>
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
      <body className={`${displayFont.variable} ${sansFont.variable} min-h-full bg-background`}>
        <Providers>{children}</Providers>
        <PWARegister />
      </body>
    </html>
  );
}
