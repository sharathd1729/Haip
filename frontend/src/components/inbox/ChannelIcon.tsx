import { MessageSquare, Phone, Globe } from "lucide-react";
import { cn } from "@/lib/utils";

type Channel = "whatsapp" | "instagram" | "web" | "sms" | "call" | string;

/** Minimal inline Instagram glyph — lucide removed it in v1+ */
function InstagramIcon({ size = 14 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="2" width="20" height="20" rx="5" ry="5" />
      <circle cx="12" cy="12" r="4" />
      <circle cx="17.5" cy="6.5" r="1" fill="currentColor" stroke="none" />
    </svg>
  );
}

const CONFIGS: Record<string, { icon: React.ReactNode; color: string; bg: string }> = {
  whatsapp:  { icon: <MessageSquare size={14} />, color: "text-green-600",  bg: "bg-green-100" },
  instagram: { icon: <InstagramIcon size={14} />, color: "text-pink-600",   bg: "bg-pink-100" },
  web:       { icon: <Globe size={14} />,         color: "text-blue-600",   bg: "bg-blue-100" },
  sms:       { icon: <MessageSquare size={14} />, color: "text-amber-600",  bg: "bg-amber-100" },
  call:      { icon: <Phone size={14} />,         color: "text-purple-600", bg: "bg-purple-100" },
};

export function ChannelIcon({ channel, className }: { channel: Channel; className?: string }) {
  const cfg = CONFIGS[channel] ?? { icon: <MessageSquare size={14} />, color: "text-gray-500", bg: "bg-gray-100" };
  return (
    <span className={cn("inline-flex w-6 h-6 rounded-md items-center justify-center flex-shrink-0", cfg.bg, cfg.color, className)}>
      {cfg.icon}
    </span>
  );
}
