import type { Metadata } from "next";

// Yaad's screens (personal workspace): the browser tab says Yaad, not HAIP.
export const metadata: Metadata = { title: "Yaad" };

export default function YaadScreensLayout({ children }: { children: React.ReactNode }) {
  return children;
}
