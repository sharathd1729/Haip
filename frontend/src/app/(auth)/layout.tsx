import type { Metadata } from "next";

export const metadata: Metadata = {
  title: {
    template: "%s | HAIP",
    default: "HAIP — Hospitality AI Intelligence Platform",
  },
  description: "Sign in to your HAIP workspace or create a new account.",
};

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
