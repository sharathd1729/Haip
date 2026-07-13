import { Sparkles, Check } from "lucide-react";
import { MockupFrame, Chip } from "./MockupFrame";

export function AiAssistantMockup({ className = "" }: { className?: string }) {
  return (
    <MockupFrame title="HAIP — AI Assistant" className={className}>
      <div className="p-3 sm:p-4 flex flex-col gap-2.5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div
              className="w-6 h-6 rounded-md flex items-center justify-center shrink-0"
              style={{ backgroundColor: "rgba(11,107,94,0.10)" }}
            >
              <Sparkles size={12} style={{ color: "var(--home-accent)" }} />
            </div>
            <p className="text-[12px] font-semibold" style={{ color: "var(--home-text)" }}>
              Draft ready for review
            </p>
          </div>
          <Chip label="WhatsApp" tone="success" />
        </div>

        <div
          className="rounded-lg border px-3 py-2.5 text-[11px] leading-relaxed"
          style={{ borderColor: "var(--home-border)", color: "var(--home-text)" }}
        >
          Hi Ananya! The Serene Pool Villa is available Nov 20–23 for 6 guests at ₹28,000/night.
          It includes breakfast and a private chef on request. Would you like me to hold it for 24 hours?
        </div>

        <div className="flex flex-col gap-1">
          {[
            "Availability checked against live calendar",
            "Rate pulled from Diwali seasonal plan",
            "Tone matched to previous conversations",
          ].map((line) => (
            <p key={line} className="text-[10px] flex items-center gap-1.5" style={{ color: "var(--home-text-muted)" }}>
              <Check size={10} className="shrink-0" style={{ color: "var(--home-success)" }} />
              {line}
            </p>
          ))}
        </div>

        <div className="flex gap-2 pt-0.5">
          <span
            className="flex-1 text-center text-[11px] font-semibold text-white rounded-lg py-1.5"
            style={{ backgroundColor: "var(--home-accent)" }}
          >
            Send reply
          </span>
          <span
            className="flex-1 text-center text-[11px] font-semibold rounded-lg py-1.5 border"
            style={{ borderColor: "var(--home-border)", color: "var(--home-text-muted)" }}
          >
            Edit first
          </span>
        </div>
      </div>
    </MockupFrame>
  );
}
