import Link from "next/link";
import { ArrowRight, Check } from "lucide-react";

const integrations = [
  { name: "WhatsApp Business", cat: "Messaging", status: "Live", desc: "Official Meta Cloud API with Embedded Signup. Connect in minutes—no developer needed.", color: "bg-green-500/15 border-green-500/20 text-green-400" },
  { name: "Instagram", cat: "Messaging", status: "Live", desc: "Instagram DMs and mentions managed from your HAIP inbox.", color: "bg-pink-500/15 border-pink-500/20 text-pink-400" },
  { name: "CallerDesk", cat: "Telephony", status: "Live", desc: "India's leading cloud telephony. Auto-transcription and QA for every call.", color: "bg-blue-500/15 border-blue-500/20 text-blue-400" },
  { name: "Acefone", cat: "Telephony", status: "Live", desc: "Multi-property cloud telephony with DID management and call flow analytics.", color: "bg-purple-500/15 border-purple-500/20 text-purple-400" },
  { name: "Servetel", cat: "Telephony", status: "Live", desc: "Enterprise-grade IVR with HAIP's AI call intelligence layer.", color: "bg-indigo-500/15 border-indigo-500/20 text-indigo-400" },
  { name: "Hostaway", cat: "PMS", status: "Coming soon", desc: "Two-way sync of bookings, guests, and inquiry data.", color: "bg-orange-500/15 border-orange-500/20 text-orange-400" },
  { name: "MakeMyTrip", cat: "OTA", status: "Coming soon", desc: "Sync bookings and guest data from MakeMyTrip listings.", color: "bg-red-500/15 border-red-500/20 text-red-400" },
  { name: "Booking.com", cat: "OTA", status: "Coming soon", desc: "Automatic guest message sync from Booking.com inbox.", color: "bg-cyan-500/15 border-cyan-500/20 text-cyan-400" },
];

export default function IntegrationsMarketingPage() {
  return (
    <div className="bg-[#0D1B4B] text-white min-h-screen pt-24">
      <div className="max-w-6xl mx-auto px-5 sm:px-8 py-16">
        <div className="text-center mb-16">
          <p className="text-xs font-bold text-indigo-400 uppercase tracking-widest mb-3">Integrations</p>
          <h1 className="text-4xl sm:text-5xl font-black tracking-tight mb-4">Works with your existing tools</h1>
          <p className="text-white/45 text-xl max-w-xl mx-auto">
            HAIP connects to the platforms you already use. Set up in minutes, not days.
          </p>
        </div>

        <div className="grid sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4 mb-16">
          {integrations.map(int => (
            <div key={int.name} className="bg-[#0f2744] border border-white/8 rounded-2xl p-5 hover:border-white/20 transition-colors">
              <div className="flex items-center justify-between mb-3">
                <span className={`text-xs font-bold px-2 py-0.5 rounded-lg border ${int.color}`}>{int.cat}</span>
                <span className={`text-[10px] font-semibold ${int.status === "Live" ? "text-green-400" : "text-white/30"}`}>
                  {int.status === "Live" ? "● Live" : "○ Coming soon"}
                </span>
              </div>
              <h3 className="text-sm font-bold text-white mb-2">{int.name}</h3>
              <p className="text-xs text-white/40 leading-relaxed">{int.desc}</p>
            </div>
          ))}
        </div>

        <div className="bg-[#0f2744] border border-indigo-500/20 rounded-2xl p-8 text-center">
          <h2 className="text-xl font-black mb-3">Don&apos;t see your tool?</h2>
          <p className="text-white/45 mb-6">We&apos;re constantly adding new integrations. Vote for what you need or reach out to our team.</p>
          <div className="flex flex-col sm:flex-row gap-3 justify-center">
            <Link href="/register" className="px-6 py-3 bg-indigo-500 hover:bg-indigo-400 text-white font-bold rounded-xl inline-flex items-center gap-2">
              Start free trial <ArrowRight size={16} />
            </Link>
            <a href="mailto:integrations@haip.app" className="px-6 py-3 bg-white/5 hover:bg-white/10 text-white font-semibold rounded-xl border border-white/10">
              Request an integration
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}
