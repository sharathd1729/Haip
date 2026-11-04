import type { ReactNode } from "react";
import { FONT_VARS } from "@/lib/font-faces";
import "@/site-blocks/site.css";
import "@/site-blocks/v2/site-v2.css";
import "@/components/consent.css";

export const viewport = { width: "device-width", initialScale: 1, viewportFit: "cover" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    // v2 fonts are self-hosted (lib/font-faces.ts); only a classic (v1) page links its pack's Google stylesheet (V1Fonts).
    <html lang="en-IN" className={FONT_VARS}>
      <body style={{ margin: 0 }}>{children}</body>
    </html>
  );
}
