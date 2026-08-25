import { TrendingUp } from "@/lib/icons";
import { MockupFrame } from "./MockupFrame";

const occupancyBars = [62, 71, 68, 79, 84, 92, 88, 95, 90, 97, 93, 98];
const channels = [
  { label: "Direct", pct: 38, color: "#0B6B5E" },
  { label: "WhatsApp", pct: 27, color: "#1F9D55" },
  { label: "OTA", pct: 22, color: "#D97706" },
  { label: "Instagram", pct: 13, color: "#8A8A85" },
];

export function AnalyticsMockup({ className = "" }: { className?: string }) {
  return (
    <MockupFrame title="HAIP — Analytics" className={className}>
      <div className="p-3 sm:p-4 flex flex-col gap-3">
        {/* KPI row */}
        <div className="grid grid-cols-3 gap-2">
          {[
            { label: "Occupancy", value: "87%", delta: "+6%" },
            { label: "ADR", value: "₹18.4K", delta: "+11%" },
            { label: "Review score", value: "4.8", delta: "+0.2" },
          ].map((k) => (
            <div
              key={k.label}
              className="rounded-lg border px-2.5 py-2"
              style={{ borderColor: "var(--home-border)" }}
            >
              <p className="text-[9px] truncate" style={{ color: "var(--home-text-subtle)" }}>
                {k.label}
              </p>
              <p className="text-[15px] font-bold leading-tight" style={{ color: "var(--home-text)" }}>
                {k.value}
              </p>
              <p className="text-[9px] font-semibold inline-flex items-center gap-0.5" style={{ color: "var(--home-success)" }}>
                <TrendingUp size={9} /> {k.delta}
              </p>
            </div>
          ))}
        </div>

        {/* Occupancy bar chart */}
        <div className="rounded-lg border p-3" style={{ borderColor: "var(--home-border)" }}>
          <div className="flex items-center justify-between mb-2">
            <p className="text-[10px] font-semibold" style={{ color: "var(--home-text)" }}>
              Occupancy — last 12 weeks
            </p>
            <p className="text-[9px]" style={{ color: "var(--home-text-subtle)" }}>
              Avg 85%
            </p>
          </div>
          <div className="flex items-end gap-1 h-16" role="img" aria-label="Occupancy trending upward over 12 weeks">
            {occupancyBars.map((v, i) => (
              <div
                key={i}
                className="flex-1 rounded-t-sm"
                style={{
                  height: `${v}%`,
                  backgroundColor: i >= 9 ? "var(--home-accent)" : "rgba(11,107,94,0.25)",
                }}
              />
            ))}
          </div>
        </div>

        {/* Channel mix */}
        <div className="rounded-lg border p-3" style={{ borderColor: "var(--home-border)" }}>
          <p className="text-[10px] font-semibold mb-2" style={{ color: "var(--home-text)" }}>
            Booking channel mix
          </p>
          <div className="flex h-2 rounded-full overflow-hidden mb-2" role="img" aria-label="Channel mix: Direct 38%, WhatsApp 27%, OTA 22%, Instagram 13%">
            {channels.map((c) => (
              <div key={c.label} style={{ width: `${c.pct}%`, backgroundColor: c.color }} />
            ))}
          </div>
          <div className="flex flex-wrap gap-x-3 gap-y-1">
            {channels.map((c) => (
              <span key={c.label} className="inline-flex items-center gap-1 text-[9px]" style={{ color: "var(--home-text-muted)" }}>
                <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: c.color }} />
                {c.label} {c.pct}%
              </span>
            ))}
          </div>
        </div>
      </div>
    </MockupFrame>
  );
}
