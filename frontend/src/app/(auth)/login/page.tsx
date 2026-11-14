"use client";
import { Suspense } from "react";
import Link from "next/link";
import { Zap, Shield, BarChart3 } from "@/lib/icons";
import { LoginForm } from "@/components/auth/LoginForm";

const SELLING_POINTS = [
  { icon: Zap, text: "AI answers every missed call, 24/7" },
  { icon: BarChart3, text: "Revenue insights from call transcripts" },
  { icon: Shield, text: "DPDP-compliant guest data handling" },
];

export default function LoginPage() {
  return (
    <div className="min-h-screen flex">
      {/* ── Left panel: always-dark brand marketing ── */}
      <div className="hidden lg:flex lg:w-[52%] flex-col justify-between bg-[var(--haip-brand-panel)] p-12 relative overflow-hidden">
        <div className="absolute inset-0 pointer-events-none">
          <div className="absolute top-[-80px] right-[-80px] w-[360px] h-[360px] rounded-full bg-[var(--haip-panel-accent)]/10 blur-3xl" />
          <div className="absolute bottom-[-60px] left-[-60px] w-[280px] h-[280px] rounded-full bg-white/5 blur-3xl" />
        </div>

        <div className="relative">
          <Link href="/" className="inline-flex items-center">
            <div className="bg-white rounded-xl px-2.5 py-1 inline-flex items-center">
              <img src="/logo-wordmark.png" alt="HAIP" className="h-6 w-auto object-contain" />
            </div>
          </Link>
        </div>

        <div className="relative space-y-10">
          <div>
            <h1 className="text-4xl font-bold text-white leading-tight mb-4">
              Your hospitality team,<br />
              <span className="text-[var(--haip-panel-accent)]">supercharged by AI</span>
            </h1>
            <p className="text-white/75 text-lg leading-relaxed max-w-sm">
              Every call answered, every guest remembered, every opportunity captured — automatically.
            </p>
          </div>

          <div className="space-y-4">
            {SELLING_POINTS.map(({ icon: Icon, text }) => (
              <div key={text} className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg bg-white/5 border border-white/10 flex items-center justify-center flex-shrink-0">
                  <Icon size={15} className="text-[var(--haip-panel-accent)]" />
                </div>
                <span className="text-white/80 text-sm">{text}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="relative">
          <div className="bg-white/5 border border-white/10 rounded-xl p-5 max-w-sm">
            <div className="flex items-center gap-1 mb-3">
              {[...Array(5)].map((_, i) => (
                <svg key={i} className="w-4 h-4 fill-[var(--haip-amber)]" viewBox="0 0 20 20">
                  <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
                </svg>
              ))}
            </div>
            <p className="text-white/80 text-sm leading-relaxed italic mb-3">
              &ldquo;HAIP cut our missed-call rate to zero. The AI handles guest queries before we even wake up.&rdquo;
            </p>
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-full bg-[var(--haip-panel-accent)]/15 border border-[var(--haip-panel-accent)]/30 flex items-center justify-center text-[var(--haip-panel-accent)] text-xs font-bold">
                RK
              </div>
              <div>
                <p className="text-white text-xs font-semibold">Rahul K.</p>
                <p className="text-white/60 text-xs">Villa manager, Goa</p>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ── Right panel: theme-adaptive form ── */}
      <div className="flex-1 flex flex-col items-center justify-center bg-background px-6 py-12">
        {/* Mobile logo */}
        <div className="lg:hidden mb-8">
          <Link href="/" className="inline-flex items-center">
            <img src="/logo-wordmark.png" alt="HAIP" className="h-8 w-auto object-contain" />
          </Link>
        </div>

        <Suspense fallback={null}>
          <LoginForm />
        </Suspense>

        <p className="mt-auto pt-12 text-xs text-muted-foreground text-center">
          © {new Date().getFullYear()} HAIP Technologies Pvt. Ltd. ·{" "}
          <Link href="/privacy" className="hover:text-foreground transition-colors">Privacy</Link>
          {" · "}
          <Link href="/terms" className="hover:text-foreground transition-colors">Terms</Link>
        </p>
      </div>
    </div>
  );
}
