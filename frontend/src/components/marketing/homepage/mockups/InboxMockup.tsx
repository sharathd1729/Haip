import { MessageSquare, Camera, Phone, Globe, Sparkles, StickyNote } from "lucide-react";
import { MockupFrame, Chip } from "./MockupFrame";

const conversations = [
  {
    name: "Ananya Sharma",
    channel: "WhatsApp",
    icon: <MessageSquare size={11} />,
    preview: "Is the pool villa available for Diwali weekend?",
    time: "2m",
    unread: true,
    tone: "success" as const,
  },
  {
    name: "Rohan Mehta",
    channel: "Instagram",
    icon: <Camera size={11} />,
    preview: "Saw your reel — do you host events?",
    time: "14m",
    unread: true,
    tone: "warning" as const,
  },
  {
    name: "Priya Nair",
    channel: "Voice AI",
    icon: <Phone size={11} />,
    preview: "Call summary: asked about corporate offsite rates",
    time: "1h",
    unread: false,
    tone: "accent" as const,
  },
  {
    name: "Booking.com guest",
    channel: "OTA",
    icon: <Globe size={11} />,
    preview: "Early check-in request for reservation #4821",
    time: "3h",
    unread: false,
    tone: "neutral" as const,
  },
];

export function InboxMockup({ className = "" }: { className?: string }) {
  return (
    <MockupFrame title="HAIP — Unified Inbox" className={className}>
      <div className="grid grid-cols-[minmax(0,1fr)] sm:grid-cols-[180px_minmax(0,1fr)]">
        {/* Conversation list */}
        <div className="border-r hidden sm:block" style={{ borderColor: "var(--home-border)" }}>
          {conversations.map((c) => (
            <div
              key={c.name}
              className="px-3 py-2.5 border-b flex flex-col gap-1"
              style={{
                borderColor: "var(--home-border)",
                backgroundColor: c.name === "Ananya Sharma" ? "rgba(11,107,94,0.05)" : "transparent",
              }}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-[11px] font-semibold truncate" style={{ color: "var(--home-text)" }}>
                  {c.name}
                </span>
                <span className="text-[9px] shrink-0" style={{ color: "var(--home-text-subtle)" }}>
                  {c.time}
                </span>
              </div>
              <div className="flex items-center gap-1.5">
                <Chip label={c.channel} tone={c.tone} />
                {c.unread && (
                  <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: "var(--home-accent)" }} />
                )}
              </div>
              <p className="text-[10px] truncate" style={{ color: "var(--home-text-muted)" }}>
                {c.preview}
              </p>
            </div>
          ))}
        </div>

        {/* Active thread */}
        <div className="p-3 sm:p-4 flex flex-col gap-2.5 min-w-0">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 min-w-0">
              <div
                className="w-7 h-7 rounded-full flex items-center justify-center text-[10px] font-bold shrink-0"
                style={{ backgroundColor: "rgba(11,107,94,0.10)", color: "var(--home-accent)" }}
              >
                AS
              </div>
              <div className="min-w-0">
                <p className="text-[12px] font-semibold truncate" style={{ color: "var(--home-text)" }}>
                  Ananya Sharma
                </p>
                <p className="text-[9px]" style={{ color: "var(--home-text-subtle)" }}>
                  Repeat guest · 2 previous stays
                </p>
              </div>
            </div>
            <Chip label="Hot lead" tone="warning" />
          </div>

          <div
            className="rounded-lg rounded-tl-sm px-3 py-2 max-w-[85%] text-[11px] leading-snug"
            style={{ backgroundColor: "#F3F3F1", color: "var(--home-text)" }}
          >
            Is the pool villa available for Diwali weekend? We&apos;re 6 adults.
          </div>

          <div
            className="rounded-lg rounded-tr-sm px-3 py-2 max-w-[85%] self-end text-[11px] leading-snug text-white"
            style={{ backgroundColor: "var(--home-accent)" }}
          >
            Yes! Serene Pool Villa is open Nov 20–23. Sleeps 8 — shall I hold it for you?
          </div>

          {/* AI suggestion */}
          <div
            className="rounded-lg px-3 py-2 border text-[10px] leading-snug flex gap-2"
            style={{ borderColor: "rgba(11,107,94,0.25)", backgroundColor: "rgba(11,107,94,0.04)" }}
          >
            <Sparkles size={12} className="shrink-0 mt-0.5" style={{ color: "var(--home-accent)" }} />
            <div>
              <p className="font-semibold mb-0.5" style={{ color: "var(--home-accent)" }}>
                Suggested reply
              </p>
              <p style={{ color: "var(--home-text-muted)" }}>
                Share the Diwali package with chef add-on — this guest booked dining both previous stays.
              </p>
            </div>
          </div>

          {/* Internal note */}
          <div
            className="rounded-lg px-3 py-2 text-[10px] flex items-center gap-2"
            style={{ backgroundColor: "rgba(217,119,6,0.07)", color: "#92610A" }}
          >
            <StickyNote size={11} className="shrink-0" />
            <span className="truncate">Internal: VIP guest — manager approval for late checkout</span>
          </div>
        </div>
      </div>
    </MockupFrame>
  );
}
