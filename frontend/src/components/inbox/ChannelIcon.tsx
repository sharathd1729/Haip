/**
 * ChannelIcon — inline source/channel icon with colour-coded container.
 *
 * Covers all 14 HAIP inquiry source values plus generic channel strings.
 * Uses explicit Tailwind light + dark: classes for theme safety.
 * All icons: 14px, inline with text, gap-1.
 */
import { MessageSquare, Phone, Globe, Building2, Users } from "lucide-react";
import { cn } from "@/lib/utils";

// ─── Inline Instagram glyph (removed from lucide v1+) ────────────────────────

function InstagramIcon({ size = 14 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <rect x="2" y="2" width="20" height="20" rx="5" ry="5" />
      <circle cx="12" cy="12" r="4" />
      <circle cx="17.5" cy="6.5" r="1" fill="currentColor" stroke="none" />
    </svg>
  );
}

// ─── Channel config ───────────────────────────────────────────────────────────

type ChannelConfig = {
  icon: React.ReactNode;
  /** Tailwind colour + dark variant classes */
  color: string;
  bg: string;
};

const CONFIGS: Record<string, ChannelConfig> = {
  // WhatsApp — emerald
  wa_direct:    { icon: <MessageSquare size={14} />, color: "text-emerald-600 dark:text-emerald-400", bg: "bg-emerald-50 dark:bg-emerald-950" },
  whatsapp:     { icon: <MessageSquare size={14} />, color: "text-emerald-600 dark:text-emerald-400", bg: "bg-emerald-50 dark:bg-emerald-950" },
  click_to_wa:  { icon: <MessageSquare size={14} />, color: "text-emerald-600 dark:text-emerald-400", bg: "bg-emerald-50 dark:bg-emerald-950" },

  // Instagram / Meta — violet
  meta_ig:      { icon: <InstagramIcon size={14} />, color: "text-violet-600 dark:text-violet-400", bg: "bg-violet-50 dark:bg-violet-950" },
  instagram:    { icon: <InstagramIcon size={14} />, color: "text-violet-600 dark:text-violet-400", bg: "bg-violet-50 dark:bg-violet-950" },

  // Phone — blue
  inbound_call:  { icon: <Phone size={14} />, color: "text-blue-600 dark:text-blue-400", bg: "bg-blue-50 dark:bg-blue-950" },
  outbound_call: { icon: <Phone size={14} />, color: "text-blue-600 dark:text-blue-400", bg: "bg-blue-50 dark:bg-blue-950" },
  call:          { icon: <Phone size={14} />, color: "text-blue-600 dark:text-blue-400", bg: "bg-blue-50 dark:bg-blue-950" },
  voice:         { icon: <Phone size={14} />, color: "text-blue-600 dark:text-blue-400", bg: "bg-blue-50 dark:bg-blue-950" },

  // OTA Airbnb — rose
  ota_airbnb:   { icon: <Building2 size={14} />, color: "text-rose-600 dark:text-rose-400", bg: "bg-rose-50 dark:bg-rose-950" },
  airbnb:       { icon: <Building2 size={14} />, color: "text-rose-600 dark:text-rose-400", bg: "bg-rose-50 dark:bg-rose-950" },

  // OTA MMT / Goibibo / Booking — red/orange
  ota_mmt:      { icon: <Building2 size={14} />, color: "text-red-600 dark:text-red-400", bg: "bg-red-50 dark:bg-red-950" },
  ota_booking:  { icon: <Building2 size={14} />, color: "text-orange-600 dark:text-orange-400", bg: "bg-orange-50 dark:bg-orange-950" },
  ota_vrbo:     { icon: <Building2 size={14} />, color: "text-sky-600 dark:text-sky-400", bg: "bg-sky-50 dark:bg-sky-950" },
  ota_goibibo:  { icon: <Building2 size={14} />, color: "text-red-600 dark:text-red-400", bg: "bg-red-50 dark:bg-red-950" },

  // Channel manager / referral / other
  channel_manager: { icon: <Building2 size={14} />, color: "text-amber-600 dark:text-amber-400", bg: "bg-amber-50 dark:bg-amber-950" },
  referral:        { icon: <Users size={14} />,     color: "text-purple-600 dark:text-purple-400", bg: "bg-purple-50 dark:bg-purple-950" },
  walk_in:         { icon: <Users size={14} />,     color: "text-teal-600 dark:text-teal-400", bg: "bg-teal-50 dark:bg-teal-950" },
  website:         { icon: <Globe size={14} />,     color: "text-blue-600 dark:text-blue-400", bg: "bg-blue-50 dark:bg-blue-950" },
  web_chat:        { icon: <Globe size={14} />,     color: "text-blue-600 dark:text-blue-400", bg: "bg-blue-50 dark:bg-blue-950" },
  web:             { icon: <Globe size={14} />,     color: "text-blue-600 dark:text-blue-400", bg: "bg-blue-50 dark:bg-blue-950" },
  sms:             { icon: <MessageSquare size={14} />, color: "text-amber-600 dark:text-amber-400", bg: "bg-amber-50 dark:bg-amber-950" },
};

const FALLBACK: ChannelConfig = {
  icon: <MessageSquare size={14} />,
  color: "text-zinc-500 dark:text-zinc-400",
  bg: "bg-zinc-100 dark:bg-zinc-800",
};

// Human-facing label per channel/source key — kept separate from CONFIGS so
// every raw backend value (call/inbound_call/outbound_call/voice, etc.) maps
// to one short word instead of the raw key leaking into the UI as literal
// text (e.g. "voice" showing where an agent expects "Call").
const LABELS: Record<string, string> = {
  wa_direct: "WhatsApp", whatsapp: "WhatsApp", click_to_wa: "WhatsApp",
  meta_ig: "Instagram", instagram: "Instagram",
  inbound_call: "Call", outbound_call: "Call", call: "Call", voice: "Call",
  ota_airbnb: "Airbnb", airbnb: "Airbnb",
  ota_mmt: "MakeMyTrip", ota_booking: "Booking.com", ota_vrbo: "Vrbo", ota_goibibo: "Goibibo",
  channel_manager: "Channel Manager", referral: "Referral", walk_in: "Walk-in",
  website: "Website", web_chat: "Website", web: "Website", sms: "SMS",
};
const FALLBACK_LABEL = "Other";

/** Human-facing label for a channel/source key — same normalization
 * ChannelIcon uses internally, exported so non-icon contexts (e.g. a plain
 * text list) can stay consistent without duplicating the map. */
export function channelLabel(channel: string): string {
  const key = channel.toLowerCase().replace(/ /g, "_");
  return LABELS[key] ?? FALLBACK_LABEL;
}

// ─── Component ────────────────────────────────────────────────────────────────

interface ChannelIconProps {
  /** Source/channel key — case-insensitive, underscores or spaces OK */
  channel: string;
  /** Show as a larger pill with visible container (default: true) */
  showBg?: boolean;
  /** Render the human-facing label ("Call", "WhatsApp", …) next to the icon */
  showLabel?: boolean;
  className?: string;
}

export function ChannelIcon({ channel, showBg = true, showLabel = false, className }: ChannelIconProps) {
  const key = channel.toLowerCase().replace(/ /g, "_");
  const cfg = CONFIGS[key] ?? FALLBACK;
  const label = LABELS[key] ?? FALLBACK_LABEL;

  const iconEl = !showBg ? (
    <span className={cn("inline-flex items-center flex-shrink-0", cfg.color, !showLabel && className)}>
      {cfg.icon}
    </span>
  ) : (
    <span
      className={cn(
        "inline-flex w-[22px] h-[22px] rounded-md items-center justify-center flex-shrink-0",
        cfg.bg,
        cfg.color,
        !showLabel && className,
      )}
    >
      {cfg.icon}
    </span>
  );

  if (!showLabel) {
    return iconEl;
  }

  return (
    <span className={cn("inline-flex items-center gap-1.5", className)}>
      {iconEl}
      <span className="text-xs font-medium" style={{ color: "var(--haip-fg-muted)" }}>{label}</span>
    </span>
  );
}
