import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Free property assessment and ROI estimate | HAIP",
  description: "What could your hotel, retreat, farmhouse or event space earn? A free revenue, investment and payback estimate.",
};

export default function AssessLayout({ children }: { children: React.ReactNode }) {
  return children;
}
