import { Sparkles, MessageSquare, Phone, Shield, Plug } from "lucide-react";

const releases = [
  {
    version: "v0.18.0", date: "May 2026", tag: "Marketing site",
    items: [
      { type: "new", text: "Launched solution pages for villas, hotels, resorts and travel operators." },
      { type: "new", text: "New Trust Center with sub-processor registry and DPDP status." },
      { type: "improved", text: "Resources mega-menu in the marketing nav (case studies, security, docs, status)." },
    ],
  },
  {
    version: "v0.17.2", date: "May 2026", tag: "AI Concierge",
    items: [
      { type: "new", text: "Brand-voice grounding from past WhatsApp + email threads (RAG)." },
      { type: "improved", text: "Confidence threshold tuned: shadow → autonomous at 0.78 on hospitality enquiries." },
      { type: "fixed", text: "Edge case where AI Concierge would propose unavailable villa dates during peak loads." },
    ],
  },
  {
    version: "v0.17.0", date: "April 2026", tag: "Call Intelligence",
    items: [
      { type: "new", text: "Whisper Large v3 self-hosted on app box — cost-mode default for tenants &gt; 1k calls/mo." },
      { type: "new", text: "Missed upsell detection — flags F&amp;B, spa, transport opportunities per call." },
      { type: "improved", text: "Sentiment + intent classifier moved to Claude Haiku — 4× faster, 80% cheaper." },
    ],
  },
  {
    version: "v0.16.4", date: "April 2026", tag: "Integrations",
    items: [
      { type: "new", text: "Acefone adapter — multi-property routing, click-to-call API, recording pull." },
      { type: "improved", text: "CallerDesk adapter retry logic for webhook hiccups." },
    ],
  },
  {
    version: "v0.16.0", date: "March 2026", tag: "Compliance",
    items: [
      { type: "new", text: "Hash-chained audit log, append-only, 5-year retention." },
      { type: "new", text: "Per-tenant KMS data keys — tenant A cannot decrypt tenant B&apos;s recordings." },
      { type: "new", text: "DPDP delete-on-request workflow with 30-day SLA." },
    ],
  },
];

const tagStyles: Record<string, React.CSSProperties> = {
  new: { backgroundColor: "rgba(0,85,90,0.08)", color: "#00555a", border: "1px solid rgba(0,85,90,0.22)" },
  improved: { backgroundColor: "rgba(0,136,143,0.08)", color: "#00888f", border: "1px solid rgba(0,136,143,0.22)" },
  fixed: { backgroundColor: "rgba(255,201,75,0.16)", color: "#a16207", border: "1px solid rgba(230,176,0,0.30)" },
};

const tagIcons: Record<string, React.ReactNode> = {
  "Marketing site": <Sparkles size={12} style={{ color: "#00555a" }} />,
  "AI Concierge": <MessageSquare size={12} style={{ color: "#00888f" }} />,
  "Call Intelligence": <Phone size={12} style={{ color: "#00555a" }} />,
  Integrations: <Plug size={12} style={{ color: "#e6b000" }} />,
  Compliance: <Shield size={12} style={{ color: "#16a34a" }} />,
};

export default function ChangelogPage() {
  return (
    <div className="min-h-screen" style={{ backgroundColor: "var(--mkt-bg)", color: "#0F172A" }}>
      <section className="relative pt-32 pb-12 overflow-hidden">
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          <div className="absolute top-1/3 left-1/2 -translate-x-1/2 w-[700px] h-[400px] rounded-full blur-[120px]" style={{ backgroundColor: "rgba(0,85,90,0.06)" }} />
          <div className="absolute inset-0" style={{ backgroundImage: "radial-gradient(circle, #00555a15 1px, transparent 1px)", backgroundSize: "28px 28px" }} />
        </div>
        <div className="relative max-w-3xl mx-auto px-5 sm:px-8 text-center">
          <div className="inline-flex items-center gap-2 rounded-full px-4 py-1.5 mb-5" style={{ backgroundColor: "rgba(0,85,90,0.07)", border: "1px solid rgba(0,85,90,0.25)" }}>
            <Sparkles size={12} style={{ color: "#00555a" }} />
            <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: "#00555a" }}>Changelog</span>
          </div>
          <h1 className="text-4xl sm:text-5xl font-black tracking-tight mb-4" style={{ color: "#0F172A" }}>What we&apos;ve been shipping</h1>
          <p className="text-lg leading-relaxed" style={{ color: "#475569" }}>Updates from the HAIP team. Bi-weekly release cadence — we ship small, often, and clearly.</p>
        </div>
      </section>

      <section className="px-5 sm:px-8 pb-24">
        <div className="max-w-3xl mx-auto space-y-10">
          {releases.map(r => (
            <article key={r.version} className="rounded-2xl p-7" style={{ backgroundColor: "#ffffff", border: "1px solid #E2E8F0", boxShadow: "0 1px 3px rgba(0,0,0,0.05)" }}>
              <div className="flex items-center gap-3 mb-5 flex-wrap">
                <h2 className="text-xl font-black" style={{ color: "#0F172A" }}>{r.version}</h2>
                <span className="text-xs" style={{ color: "#CBD5E1" }}>·</span>
                <span className="text-xs" style={{ color: "#64748B" }}>{r.date}</span>
                <span className="inline-flex items-center gap-1.5 ml-auto rounded-md px-2 py-0.5 text-[11px] font-semibold" style={{ backgroundColor: "#F8FAFC", border: "1px solid #E2E8F0", color: "#475569" }}>
                  {tagIcons[r.tag] ?? <Sparkles size={12} style={{ color: "#00555a" }} />} {r.tag}
                </span>
              </div>
              <ul className="space-y-2.5">
                {r.items.map((item, i) => (
                  <li key={i} className="flex items-start gap-3">
                    <span className="inline-block text-[10px] font-bold uppercase tracking-widest rounded-md px-2 py-0.5 flex-shrink-0 mt-0.5" style={tagStyles[item.type]}>{item.type}</span>
                    <p className="text-sm leading-relaxed" style={{ color: "#475569" }} dangerouslySetInnerHTML={{ __html: item.text }} />
                  </li>
                ))}
              </ul>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

export const metadata = { title: "HAIP Changelog — What we&apos;ve been shipping" };
