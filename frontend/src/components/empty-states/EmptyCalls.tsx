import Link from "next/link";
import { Phone, BarChart2, ArrowRight } from "@/lib/icons";
import { Plug2 } from "lucide-react";

export function EmptyCalls() {
  return (
    <div className="flex flex-col items-center justify-center h-full min-h-[60vh] px-6 py-16 text-center">
      <div className="w-20 h-20 rounded-3xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-center mb-6">
        <Phone size={32} className="text-blue-400/60" />
      </div>
      <h2 className="text-xl font-bold text-gray-900 mb-2">No calls yet</h2>
      <p className="text-gray-400 text-sm max-w-sm leading-relaxed mb-8">
        Connect your IVR provider (CallerDesk, Acefone, or Servetel) to automatically receive call logs, transcriptions, and AI QA scores.
      </p>
      <div className="grid sm:grid-cols-3 gap-3 max-w-md mb-8 text-left">
        {[
          { icon: <Phone size={14} className="text-blue-400" />, label: "Auto-transcription", desc: "Every call transcribed in Indian English" },
          { icon: <BarChart2 size={14} className="text-purple-400" />, label: "QA scoring", desc: "Automated agent quality review" },
          { icon: <ArrowRight size={14} className="text-teal-400" />, label: "Revenue insights", desc: "Missed opportunities surfaced" },
        ].map(item => (
          <div key={item.label} className="bg-gray-50 rounded-xl p-3 border border-gray-100">
            <div className="flex items-center gap-1.5 mb-1">{item.icon}<span className="text-xs font-bold text-gray-700">{item.label}</span></div>
            <p className="text-[11px] text-gray-400">{item.desc}</p>
          </div>
        ))}
      </div>
      <Link
        href="/dashboard/settings/integrations"
        className="inline-flex items-center gap-2 px-5 py-2.5 bg-[#0F766E] hover:bg-[#0d6660] text-white text-sm font-semibold rounded-xl transition-colors"
      >
        <Plug2 size={15} /> Connect IVR provider
      </Link>
    </div>
  );
}
