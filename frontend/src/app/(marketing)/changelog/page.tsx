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

const tagStyles: Record<string, string> = {
  new: "bg-indigo-500/15 text-indigo-300 border-indigo-500/25",
  improved: "bg-blue-500/15 text-blue-300 border-blue-500/25",
  fixed: "bg-amber-500/15 text-amber-300 border-amber-500/25",
};

const tagIcons: Record<string, React.ReactNode> = {
  "Marketing site": <Sparkles size={12} className="text-indigo-400" />,
  "AI Concierge": <MessageSquare size={12} className="text-cyan-400" />,
  "Call Intelligence": <Phone size={12} className="text-purple-400" />,
  Integrations: <Plug size={12} className="text-amber-400" />,
  Compliance: <Shield size={12} className="text-green-400" />,
};

export default function ChangelogPage() {
  return (
    <div className="bg-[#0D1B4B] text-white min-h-screen">
      <section className="relative pt-32 pb-12 overflow-hidden">
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          <div className="absolute top-1/3 left-1/2 -translate-x-1/2 w-[700px] h-[400px] rounded-full bg-purple-500/8 blur-[120px]" />
        </div>
        <div className="relative max-w-3xl mx-auto px-5 sm:px-8 text-center">
          <div className="inline-flex items-center gap-2 bg-purple-500/10 border border-purple-500/20 rounded-full px-4 py-1.5 mb-5">
            <Sparkles size={12} className="text-purple-400" />
            <span className="text-xs font-semibold text-purple-300 uppercase tracking-wider">Changelog</span>
          </div>
          <h1 className="text-4xl sm:text-5xl font-black tracking-tight mb-4">What we&apos;ve been shipping</h1>
          <p className="text-white/55 text-lg leading-relaxed">Updates from the HAIP team. Bi-weekly release cadence — we ship small, often, and clearly.</p>
        </div>
      </section>

      <section className="px-5 sm:px-8 pb-24">
        <div className="max-w-3xl mx-auto space-y-10">
          {releases.map(r => (
            <article key={r.version} className="bg-[#0f2744]/70 border border-white/8 rounded-2xl p-7">
              <div className="flex items-center gap-3 mb-5 flex-wrap">
                <h2 className="text-xl font-black text-white">{r.version}</h2>
                <span className="text-xs text-white/35">·</span>
                <span className="text-xs text-white/45">{r.date}</span>
                <span className="inline-flex items-center gap-1.5 ml-auto bg-white/5 border border-white/10 rounded-md px-2 py-0.5 text-[11px] font-semibold text-white/70">
                  {tagIcons[r.tag] ?? <Sparkles size={12} className="text-indigo-400" />} {r.tag}
                </span>
              </div>
              <ul className="space-y-2.5">
                {r.items.map((item, i) => (
                  <li key={i} className="flex items-start gap-3">
                    <span className={`inline-block text-[10px] font-bold uppercase tracking-widest border rounded-md px-2 py-0.5 flex-shrink-0 mt-0.5 ${tagStyles[item.type]}`}>{item.type}</span>
                    <p className="text-sm text-white/65 leading-relaxed" dangerouslySetInnerHTML={{ __html: item.text }} />
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
