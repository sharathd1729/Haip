import type { Metadata } from "next";
import Link from "next/link";
import { YaadWordmark } from "@/components/personal/YaadMark";

export const metadata: Metadata = {
  title: { template: "%s | Yaad", default: "Yaad — remember every call" },
  description: "Sign in to Yaad: your calls, summarised, with every promise and plan remembered.",
};

// Yaad's sign-in and sign-up (a personal workspace: one person's own calls). Mango theme, phone first.
export default function YaadAuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="yaad yaad-auth flex min-h-[100dvh] flex-col items-center px-4 py-10">
      <YaadWordmark className="mb-8" />
      <main className="w-full max-w-sm rounded-[24px] border border-[var(--y-line)] bg-[var(--y-card)] p-6 shadow-[var(--y-shadow)] sm:p-8">
        {children}
      </main>
      <p className="mt-auto pt-10 text-center text-xs text-[var(--y-ink-3)]">
        Yaad by HAIP ·{" "}
        <Link href="/privacy" className="underline-offset-2 hover:underline">Privacy</Link>
        {" · "}
        <Link href="/terms" className="underline-offset-2 hover:underline">Terms</Link>
      </p>
    </div>
  );
}
