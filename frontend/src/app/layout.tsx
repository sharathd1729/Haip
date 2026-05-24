import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { Providers } from "@/components/providers";
import { PWARegister } from "@/components/PWARegister";

const inter = Inter({ subsets: ["latin"] });

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  themeColor: "#0a1b30",
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
    <html lang="en" className="h-full antialiased">
      {/* Inline script runs before paint — prevents dark/light flash */}
      <head>
        <script dangerouslySetInnerHTML={{ __html: `
          try {
            var s = localStorage.getItem('haip_color_scheme');
            if (s !== 'light') document.documentElement.classList.add('dark');
          } catch(e) {
            document.documentElement.classList.add('dark');
          }
        `}} />
      </head>
      <body className={`${inter.className} min-h-full bg-background`}>
        <Providers>{children}</Providers>
        <PWARegister />
      </body>
    </html>
  );
}
