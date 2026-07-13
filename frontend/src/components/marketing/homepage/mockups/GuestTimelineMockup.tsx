import { MessageSquare, Phone, CalendarCheck2, Star, Camera } from "lucide-react";
import { MockupFrame, Chip } from "./MockupFrame";

const events = [
  {
    icon: <Camera size={11} />,
    title: "Instagram DM inquiry",
    detail: "Asked about villa availability",
    time: "Oct 2",
    tone: "warning" as const,
  },
  {
    icon: <Phone size={11} />,
    title: "Voice AI call",
    detail: "Discussed rates · summary attached",
    time: "Oct 3",
    tone: "accent" as const,
  },
  {
    icon: <MessageSquare size={11} />,
    title: "WhatsApp quote sent",
    detail: "Diwali package · ₹84,000",
    time: "Oct 4",
    tone: "success" as const,
  },
  {
    icon: <CalendarCheck2 size={11} />,
    title: "Booking confirmed",
    detail: "Nov 20–23 · advance received",
    time: "Oct 5",
    tone: "accent" as const,
  },
  {
    icon: <Star size={11} />,
    title: "5-star review posted",
    detail: "Google · auto-thanked",
    time: "Nov 25",
    tone: "success" as const,
  },
];

export function GuestTimelineMockup({ className = "" }: { className?: string }) {
  return (
    <MockupFrame title="HAIP — Guest Timeline" className={className}>
      <div className="p-3 sm:p-4">
        <div className="flex items-center justify-between mb-3">
          <p className="text-[12px] font-semibold" style={{ color: "var(--home-text)" }}>
            Ananya Sharma — journey
          </p>
          <Chip label="Inquiry → Booked" tone="accent" />
        </div>
        <div className="relative pl-5">
          <span
            className="absolute left-[7px] top-1 bottom-1 w-px"
            style={{ backgroundColor: "var(--home-border)" }}
            aria-hidden="true"
          />
          <div className="flex flex-col gap-3">
            {events.map((e) => (
              <div key={e.title} className="relative">
                <span
                  className="absolute -left-5 top-0.5 w-[15px] h-[15px] rounded-full flex items-center justify-center"
                  style={{ backgroundColor: "rgba(11,107,94,0.10)", color: "var(--home-accent)" }}
                >
                  {e.icon}
                </span>
                <div className="flex items-baseline justify-between gap-2">
                  <p className="text-[11px] font-semibold truncate" style={{ color: "var(--home-text)" }}>
                    {e.title}
                  </p>
                  <span className="text-[9px] shrink-0" style={{ color: "var(--home-text-subtle)" }}>
                    {e.time}
                  </span>
                </div>
                <p className="text-[10px] truncate" style={{ color: "var(--home-text-muted)" }}>
                  {e.detail}
                </p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </MockupFrame>
  );
}
