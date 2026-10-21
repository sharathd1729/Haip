import type { ReactNode } from "react";
import { FONTS_HREF } from "@/site-blocks/packs";
import "@/site-blocks/site.css";

export const viewport = { width: "device-width", initialScale: 1, viewportFit: "cover" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en-IN">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link rel="stylesheet" href={FONTS_HREF} />
      </head>
      <body style={{ margin: 0 }}>{children}</body>
    </html>
  );
}
