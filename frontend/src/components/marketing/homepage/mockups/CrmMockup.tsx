import { Star, CalendarCheck2 } from "lucide-react";
import { MockupFrame, Chip } from "./MockupFrame";
import { CountUp } from "../shared/CountUp";

export function CrmMockup({ className = "" }: { className?: string }) {
  return (
    <MockupFrame title="HAIP — Guest Profile" className={className}>
      <div className="p-3 sm:p-4 flex flex-col gap-3">
        {/* Header */}
        <div className="flex items-center gap-3">
          <div
            className="w-10 h-10 rounded-full flex items-center justify-center text-xs font-bold shrink-0"
            style={{ backgroundColor: "rgba(11,107,94,0.10)", color: "var(--home-accent)" }}
          >
            VK
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-[13px] font-semibold truncate" style={{ color: "var(--home-text)" }}>
              Vikram Kapoor
            </p>
            <div className="flex items-center gap-1 flex-wrap mt-0.5">
              <Chip label="VIP" tone="warning" />
              <Chip label="Repeat guest" tone="accent" />
              <Chip label="Positive sentiment" tone="success" />
            </div>
          </div>
        </div>

        {/* Stats row */}
        <div
          className="grid grid-cols-4 rounded-lg border divide-x"
          style={{ borderColor: "var(--home-border)" }}
        >
          {[
            { label: "Stays", value: <CountUp to={5} /> },
            { label: "Messages", value: <CountUp to={62} /> },
            { label: "Revenue", value: <>₹4.2L</> },
            { label: "Rating", value: <>4.9</> },
          ].map((s) => (
            <div key={s.label} className="text-center py-2.5" style={{ borderColor: "var(--home-border)" }}>
              <p className="text-[15px] font-bold" style={{ color: "var(--home-text)" }}>
                {s.value}
              </p>
              <p className="text-[9px] mt-0.5" style={{ color: "var(--home-text-subtle)" }}>
                {s.label}
              </p>
            </div>
          ))}
        </div>

        {/* Preferences */}
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-wider mb-1.5" style={{ color: "var(--home-text-subtle)" }}>
            Preferences
          </p>
          <div className="flex flex-wrap gap-1">
            {["Sea-view room", "Private chef", "Late checkout", "Vegetarian"].map((p) => (
              <Chip key={p} label={p} tone="neutral" />
            ))}
          </div>
        </div>

        {/* Upcoming booking */}
        <div
          className="rounded-lg border px-3 py-2.5 flex items-center gap-2.5"
          style={{ borderColor: "rgba(11,107,94,0.25)", backgroundColor: "rgba(11,107,94,0.04)" }}
        >
          <CalendarCheck2 size={14} className="shrink-0" style={{ color: "var(--home-accent)" }} />
          <div className="min-w-0 flex-1">
            <p className="text-[11px] font-semibold truncate" style={{ color: "var(--home-text)" }}>
              Serene Pool Villa · Dec 24–27
            </p>
            <p className="text-[9px]" style={{ color: "var(--home-text-muted)" }}>
              Confirmed · ₹96,000 · Airport pickup arranged
            </p>
          </div>
          <Chip label="Confirmed" tone="success" />
        </div>

        {/* Latest review */}
        <div className="rounded-lg border px-3 py-2.5" style={{ borderColor: "var(--home-border)" }}>
          <div className="flex items-center gap-1 mb-1">
            {[...Array(5)].map((_, i) => (
              <Star key={i} size={10} fill="#D97706" style={{ color: "#D97706" }} />
            ))}
            <span className="text-[9px] ml-1" style={{ color: "var(--home-text-subtle)" }}>
              Google · Oct 2025
            </span>
          </div>
          <p className="text-[10px] leading-snug" style={{ color: "var(--home-text-muted)" }}>
            &ldquo;Impeccable service. The team remembered every detail from our last stay.&rdquo;
          </p>
        </div>
      </div>
    </MockupFrame>
  );
}
