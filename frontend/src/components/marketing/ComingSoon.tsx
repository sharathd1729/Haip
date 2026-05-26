import Link from "next/link";
import { ArrowRight, Mail, MessageSquare } from "lucide-react";
import type { ReactNode } from "react";

interface ComingSoonProps {
  eyebrow: string;
  title: string;
  description: string;
  icon: ReactNode;
  accent?: "teal" | "cyan" | "amber" | "purple" | "green";
  primaryCta?: { label: string; href: string };
  secondaryCta?: { label: string; href: string };
  highlights?: { title: string; desc: string }[];
}

const accentMap = {
  teal: { ring: "border-teal-500/30", glow: "from-teal-500/20", text: "text-teal-400", bg: "bg-teal-500/10", border: "border-teal-500/20" },
  cyan: { ring: "border-cyan-500/30", glow: "from-cyan-500/20", text: "text-cyan-400", bg: "bg-cyan-500/10", border: "border-cyan-500/20" },
  amber: { ring: "border-amber-500/30", glow: "from-amber-500/20", text: "text-amber-400", bg: "bg-amber-500/10", border: "border-amber-500/20" },
  purple: { ring: "border-purple-500/30", glow: "from-purple-500/20", text: "text-purple-400", bg: "bg-purple-500/10", border: "border-purple-500/20" },
  green: { ring: "border-green-500/30", glow: "from-green-500/20", text: "text-green-400", bg: "bg-green-500/10", border: "border-green-500/20" },
};

export function ComingSoon({
  eyebrow, title, description, icon, accent = "teal",
  primaryCta = { label: "Start free trial", href: "/register" },
  secondaryCta = { label: "Book a demo", href: "/book-demo" },
  highlights = [],
}: ComingSoonProps) {
  const a = accentMap[accent];
  return (
    <div className="bg-[var(--mkt-bg)] text-white min-h-screen">
      <section className="relative pt-32 pb-20 overflow-hidden">
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          <div className={`absolute top-1/3 left-1/2 -translate-x-1/2 w-[700px] h-[400px] rounded-full ${a.glow.replace("from-", "bg-").replace("/20", "/8")} blur-[120px]`} />
          <div className="absolute inset-0 opacity-[0.03]" style={{ backgroundImage: "radial-gradient(circle, #fff 1px, transparent 1px)", backgroundSize: "32px 32px" }} />
        </div>
        <div className="relative max-w-3xl mx-auto px-5 sm:px-8 text-center">
          <div className={`inline-flex items-center gap-2 ${a.bg} border ${a.border} rounded-full px-4 py-1.5 mb-6`}>
            <span className={a.text}>{icon}</span>
            <span className={`text-xs font-semibold ${a.text} uppercase tracking-wider`}>{eyebrow}</span>
          </div>
          <h1 className="text-4xl sm:text-5xl font-black tracking-tight leading-[1.05] mb-5">{title}</h1>
          <p className="text-white/55 text-lg leading-relaxed mb-10 max-w-xl mx-auto">{description}</p>

          {highlights.length > 0 && (
            <div className="grid sm:grid-cols-2 gap-3 mb-10 text-left">
              {highlights.map(h => (
                <div key={h.title} className="bg-[var(--mkt-panel)]/60 border border-white/8 rounded-2xl p-5">
                  <h3 className={`text-sm font-bold ${a.text} mb-1.5`}>{h.title}</h3>
                  <p className="text-xs text-white/45 leading-relaxed">{h.desc}</p>
                </div>
              ))}
            </div>
          )}

          <div className="flex flex-col sm:flex-row items-center justify-center gap-3 mb-8">
            <Link href={primaryCta.href} className="inline-flex items-center gap-2 px-6 py-3 bg-[#C8964A] hover:bg-[#D4A85A] text-[#0E1210] font-bold rounded-2xl transition-all shadow-xl shadow-[#C8964A]/30">
              {primaryCta.label} <ArrowRight size={16} />
            </Link>
            <Link href={secondaryCta.href} className="inline-flex items-center gap-2 px-6 py-3 bg-white/5 hover:bg-white/10 text-white font-semibold rounded-2xl border border-white/10 transition-all">
              {secondaryCta.label}
            </Link>
          </div>

          <div className="flex flex-col sm:flex-row items-center justify-center gap-2 text-xs text-white/35">
            <a href="mailto:hello@haip.app" className="inline-flex items-center gap-1.5 hover:text-white transition-colors">
              <Mail size={12} /> hello@haip.app
            </a>
            <span className="hidden sm:inline">·</span>
            <a href="https://wa.me/918147698153" target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 hover:text-white transition-colors">
              <MessageSquare size={12} /> WhatsApp +91 81476 98153
            </a>
          </div>
        </div>
      </section>
    </div>
  );
}
