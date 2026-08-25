import { TrendingUp, IndianRupee } from "@/lib/icons";
import { MockupFrame, Chip } from "./MockupFrame";

const monthly = [42, 48, 45, 56, 61, 58, 67, 72, 78, 74, 85, 92];

export function RevenueMockup({ className = "" }: { className?: string }) {
  return (
    <MockupFrame title="HAIP — Revenue" className={className}>
      <div className="p-3 sm:p-4 flex flex-col gap-3">
        <div className="flex items-start justify-between gap-2">
          <div>
            <p className="text-[10px]" style={{ color: "var(--home-text-subtle)" }}>
              Revenue this quarter
            </p>
            <p className="text-xl font-bold flex items-center" style={{ color: "var(--home-text)" }}>
              <IndianRupee size={16} className="shrink-0" />
              24.6L
            </p>
          </div>
          <Chip label="+18% vs last quarter" tone="success" />
        </div>

        {/* Sparkline-style bars */}
        <div className="flex items-end gap-[3px] h-14" role="img" aria-label="Monthly revenue trending upward">
          {monthly.map((v, i) => (
            <div
              key={i}
              className="flex-1 rounded-t-[2px]"
              style={{
                height: `${v}%`,
                backgroundColor: i >= 10 ? "var(--home-accent)" : "rgba(11,107,94,0.22)",
              }}
            />
          ))}
        </div>

        <div className="flex flex-col gap-1.5">
          {[
            { label: "Direct bookings", value: "₹9.3L", note: "+31%" },
            { label: "Upsells & add-ons", value: "₹2.1L", note: "+24%" },
            { label: "Repeat guests", value: "₹6.8L", note: "+12%" },
          ].map((r) => (
            <div
              key={r.label}
              className="flex items-center justify-between rounded-lg border px-2.5 py-1.5"
              style={{ borderColor: "var(--home-border)" }}
            >
              <span className="text-[10px]" style={{ color: "var(--home-text-muted)" }}>
                {r.label}
              </span>
              <span className="text-[11px] font-semibold flex items-center gap-1.5" style={{ color: "var(--home-text)" }}>
                {r.value}
                <span className="text-[9px] font-semibold inline-flex items-center gap-0.5" style={{ color: "var(--home-success)" }}>
                  <TrendingUp size={9} /> {r.note}
                </span>
              </span>
            </div>
          ))}
        </div>
      </div>
    </MockupFrame>
  );
}
