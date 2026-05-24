import Link from "next/link";
import { ArrowRight, Inbox, Phone, Users, MessageSquare, Star, BarChart2 } from "lucide-react";

const features = [
  { id: "inbox", icon: <Inbox size={24} />, title: "Unified Inbox", color: "text-teal-400", desc: "All guest communication channels in one place. WhatsApp, Instagram DMs, and calls unified with full history and AI-powered suggested replies.", benefits: ["WhatsApp Business API (Meta official)", "Instagram DMs & mentions", "Phone call thread with transcript", "AI reply suggestions", "Team assignment & handoffs"] },
  { id: "calls", icon: <Phone size={24} />, title: "AI Call Intelligence", color: "text-purple-400", desc: "Every call transcribed, scored, and analyzed automatically. Surface missed revenue, coaching opportunities, and guest signals—without listening to a single recording.", benefits: ["Auto-transcription in Indian English", "Agent QA scoring (0–100)", "Sentiment analysis", "Missed revenue opportunity flags", "Integrates with CallerDesk, Acefone, Servetel, MCube"] },
  { id: "crm", icon: <Users size={24} />, title: "Hospitality CRM", color: "text-blue-400", desc: "A CRM purpose-built for hospitality. Guest profiles, property management, inquiry tracking, and booking history—all connected.", benefits: ["Rich guest profiles with communication history", "Property & villa management", "Inquiry pipeline with Kanban view", "Stay history & preferences", "Hostaway & PMS sync"] },
  { id: "whatsapp", icon: <MessageSquare size={24} />, title: "WhatsApp Automation", color: "text-green-400", desc: "Send targeted campaigns, automate booking confirmations, and run drip sequences via WhatsApp—using the official Meta Cloud API.", benefits: ["Bulk broadcast to opted-in guests", "Template message library", "Automated booking confirmations", "No-code campaign builder", "Meta Embedded Signup (no developer needed)"] },
  { id: "qa", icon: <Star size={24} />, title: "Auto QA & Compliance", color: "text-amber-400", desc: "Automated quality review for every guest interaction. DPDP-compliant archiving. No manual audit required.", benefits: ["100% call coverage scoring", "Customizable QA rubrics", "DPDP-compliant archiving", "Agent performance trends", "Exportable compliance reports"] },
  { id: "insights", icon: <BarChart2 size={24} />, title: "AI Insights", color: "text-cyan-400", desc: "Revenue intelligence and demand forecasting from your call and message data. Know what guests want before they ask.", benefits: ["Demand pattern analysis", "Revenue gap identification", "Agent coaching recommendations", "Seasonal trend detection", "Weekly insights digest"] },
];

export default function FeaturesPage() {
  return (
    <div className="bg-[#0E1210] text-white pt-24 min-h-screen">
      <div className="max-w-7xl mx-auto px-5 sm:px-8 py-16">
        <div className="text-center mb-16">
          <p className="text-xs font-bold text-[#3D9E7E] uppercase tracking-widest mb-3">Features</p>
          <h1 className="text-4xl sm:text-5xl font-black tracking-tight mb-4">Everything your team needs</h1>
          <p className="text-white/45 text-lg max-w-xl mx-auto">One platform, built specifically for luxury hospitality operations.</p>
        </div>
        <div className="space-y-16">
          {features.map((f, i) => (
            <div key={f.id} id={f.id} className={`grid lg:grid-cols-2 gap-12 items-center ${i % 2 === 1 ? "lg:grid-flow-dense" : ""}`}>
              <div className={i % 2 === 1 ? "lg:col-start-2" : ""}>
                <div className={`w-12 h-12 rounded-xl bg-white/5 flex items-center justify-center mb-4 ${f.color}`}>{f.icon}</div>
                <h2 className="text-2xl sm:text-3xl font-black mb-3">{f.title}</h2>
                <p className="text-white/50 text-base leading-relaxed mb-6">{f.desc}</p>
                <ul className="space-y-2.5 mb-6">
                  {f.benefits.map(b => (
                    <li key={b} className="flex items-center gap-2.5 text-sm text-white/60">
                      <div className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${f.color.replace("text-", "bg-")}`} /> {b}
                    </li>
                  ))}
                </ul>
                <Link href="/register" className="inline-flex items-center gap-2 text-teal-400 hover:text-teal-300 font-semibold text-sm">
                  Try free for 14 days <ArrowRight size={14} />
                </Link>
              </div>
              <div className={`bg-[#141B15] rounded-2xl border border-white/8 p-8 flex items-center justify-center min-h-[240px] ${i % 2 === 1 ? "lg:col-start-1 lg:row-start-1" : ""}`}>
                <div className={`text-center ${f.color}`}>
                  {f.icon}
                  <p className="text-xs text-white/30 mt-3">{f.title} visualization</p>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
