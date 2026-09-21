"use client";
// Brand-coloured channel badges (Instagram / WhatsApp / Call). Used under a
// guest's avatar to show every channel they've talked to us on -- a guest
// who shared a number in an Instagram DM and was then called shows both.
import { cn } from "@/lib/utils";
import type { GuestChannel } from "@/store/inbox";
import { CallIcon, InstagramIcon, WhatsAppIcon } from "./ChannelIcon";

const META: Record<GuestChannel, { label: string; bg: string; Glyph: typeof CallIcon }> = {
  instagram: { label: "Instagram", bg: "#D62976", Glyph: InstagramIcon },
  whatsapp:  { label: "WhatsApp",  bg: "#25D366", Glyph: WhatsAppIcon },
  call:      { label: "Call",      bg: "#2563EB", Glyph: CallIcon },
};

/** Maps a conversation/message channel value to a badge key. */
export function toGuestChannel(channel?: string | null): GuestChannel | null {
  if (!channel) return null;
  if (channel === "instagram" || channel === "meta_ig") return "instagram";
  if (channel === "whatsapp" || channel === "wa_direct" || channel === "click_to_wa") return "whatsapp";
  if (channel === "voice" || channel === "call" || channel.endsWith("_call")) return "call";
  return null;
}

export function ChannelBadge({ channel, size = 16, className }: { channel: GuestChannel; size?: number; className?: string }) {
  const { label, bg, Glyph } = META[channel];
  return (
    <span
      title={label}
      aria-label={label}
      className={cn("inline-flex items-center justify-center rounded-full text-white flex-shrink-0", className)}
      style={{ width: size, height: size, background: bg }}
    >
      <Glyph size={Math.round(size * 0.62)} />
    </span>
  );
}

/** A row of badges, one per channel, in a stable order. */
export function ChannelBadges({
  channels, size = 14, className,
}: { channels?: GuestChannel[] | null; size?: number; className?: string }) {
  if (!channels?.length) return null;
  return (
    <span className={cn("inline-flex items-center gap-0.5", className)}>
      {channels.map(ch => <ChannelBadge key={ch} channel={ch} size={size} />)}
    </span>
  );
}

/** "Talked on" list with labels: [icon] Instagram  [icon] Call */
export function TalkedOn({ channels, size = 16 }: { channels?: GuestChannel[] | null; size?: number }) {
  if (!channels?.length) return null;
  return (
    <span className="inline-flex flex-wrap items-center gap-x-3 gap-y-1">
      {channels.map(ch => (
        <span key={ch} className="inline-flex items-center gap-1.5 text-xs font-semibold" style={{ color: "var(--haip-fg-2, var(--haip-fg))" }}>
          <ChannelBadge channel={ch} size={size} />
          {META[ch].label}
        </span>
      ))}
    </span>
  );
}

export function channelLabel(channel: GuestChannel): string {
  return META[channel].label;
}
