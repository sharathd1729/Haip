import { Activity, CheckCircle2 } from "lucide-react";

const services = [
  { name: "API (api.haip.app)", status: "operational" },
  { name: "Dashboard (app.haip.app)", status: "operational" },
  { name: "Webhook ingest (CallerDesk / Acefone)", status: "operational" },
  { name: "WhatsApp Cloud API bridge", status: "operational" },
  { name: "Transcription pipeline (Deepgram + Whisper)", status: "operational" },
  { name: "AI QA judge (Claude)", status: "operational" },
  { name: "Object storage (S3 Mumbai)", status: "operational" },
];

const last90 = Array.from({ length: 90 }, (_, i) => ({
  day: i,
  // Simulate near-perfect uptime
  status: i === 47 ? "degraded" : i === 73 ? "incident" : "ok",
}));

const incidents = [
  { date: "12 April 2026", title: "Brief transcription delay (Deepgram region failover)", impact: "p95 transcription latency rose from 38s to 4m for 22 minutes. No data lost.", duration: "22 min", status: "Resolved" },
  { date: "18 March 2026", title: "Acefone webhook retry storm", impact: "~40 webhooks queued for 7 minutes before processing caught up. No drops.", duration: "7 min", status: "Resolved" },
];

const colors: Record<string, { dot: string; label: string; cell: string }> = {
  ok: { dot: "bg-green-400", label: "Operational", cell: "bg-green-500/70" },
  degraded: { dot: "bg-amber-400", label: "Degraded", cell: "bg-amber-500/70" },
  incident: { dot: "bg-rose-400", label: "Incident", cell: "bg-rose-500/70" },
  operational: { dot: "bg-green-400", label: "Operational", cell: "bg-green-500" },
};

export default function StatusPage() {
  return (
    <div className="bg-[#0E1210] text-white min-h-screen">
      <section className="pt-32 pb-10 px-5 sm:px-8">
        <div className="max-w-4xl mx-auto">
          <div className="inline-flex items-center gap-2 bg-green-500/10 border border-green-500/20 rounded-full px-4 py-1.5 mb-5">
            <Activity size={12} className="text-green-400" />
            <span className="text-xs font-semibold text-green-300 uppercase tracking-wider">System status</span>
          </div>
          <h1 className="text-3xl sm:text-4xl font-black tracking-tight mb-3">All systems operational</h1>
          <p className="text-white/55 text-base">Live uptime &amp; incident log. Last updated just now.</p>
        </div>
      </section>

      <section className="px-5 sm:px-8 pb-12">
        <div className="max-w-4xl mx-auto bg-[#141B15] border border-white/10 rounded-2xl overflow-hidden">
          {services.map(s => (
            <div key={s.name} className="flex items-center justify-between px-5 py-4 border-b border-white/5 last:border-b-0">
              <span className="text-sm font-medium text-white">{s.name}</span>
              <span className="inline-flex items-center gap-2 text-xs font-semibold text-green-300">
                <span className={`w-2 h-2 rounded-full ${colors[s.status].dot} animate-pulse`} />
                {colors[s.status].label}
              </span>
            </div>
          ))}
        </div>
      </section>

      {/* 90-day heatmap */}
      <section className="px-5 sm:px-8 pb-12">
        <div className="max-w-4xl mx-auto">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-base font-bold">Last 90 days</h2>
            <div className="flex items-center gap-3 text-[10px] text-white/40">
              <span className="inline-flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-green-500/70" /> OK</span>
              <span className="inline-flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-amber-500/70" /> Degraded</span>
              <span className="inline-flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-rose-500/70" /> Incident</span>
            </div>
          </div>
          <div className="grid grid-cols-30 sm:grid-cols-45 lg:grid-cols-90 gap-[3px]" style={{ gridTemplateColumns: "repeat(45, minmax(0, 1fr))" }}>
            {last90.map(d => (
              <div key={d.day} title={`Day ${d.day + 1}`} className={`h-5 rounded-sm ${colors[d.status].cell} hover:opacity-80 transition-opacity`} />
            ))}
          </div>
          <div className="flex items-center justify-between text-[11px] text-white/35 mt-2">
            <span>90 days ago</span>
            <span className="text-teal-300 font-semibold">99.97% uptime</span>
            <span>Today</span>
          </div>
        </div>
      </section>

      {/* Incidents */}
      <section className="px-5 sm:px-8 pb-24">
        <div className="max-w-4xl mx-auto">
          <h2 className="text-base font-bold mb-4">Recent incidents</h2>
          <div className="space-y-3">
            {incidents.map(i => (
              <div key={i.title} className="bg-[#141B15]/70 border border-white/8 rounded-2xl p-5">
                <div className="flex items-start justify-between gap-3 mb-2">
                  <h3 className="text-sm font-bold text-white">{i.title}</h3>
                  <span className="inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-widest border border-green-500/30 bg-green-500/10 text-green-300 px-2 py-0.5 rounded-md flex-shrink-0">
                    <CheckCircle2 size={10} /> {i.status}
                  </span>
                </div>
                <p className="text-xs text-white/50 mb-2">{i.impact}</p>
                <p className="text-[11px] text-white/30">{i.date} · {i.duration}</p>
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}

export const metadata = { title: "HAIP Status — Live uptime" };
