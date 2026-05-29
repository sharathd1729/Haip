import { memo } from "react";
import { cn } from "@/lib/utils";

interface GuestAvatarProps {
  name?: string | null;
  phone?: string | null;
  size?: "sm" | "md" | "lg";
  className?: string;
}

const SIZE = {
  sm: "w-7 h-7 text-xs",
  md: "w-9 h-9 text-sm",
  lg: "w-12 h-12 text-base",
};

// Deterministic color from phone/name
function avatarColor(seed: string) {
  const colors = [
    "from-teal-400 to-teal-600",
    "from-blue-400 to-blue-600",
    "from-purple-400 to-purple-600",
    "from-amber-400 to-amber-600",
    "from-rose-400 to-rose-600",
    "from-cyan-400 to-cyan-600",
  ];
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) & 0xffff;
  return colors[h % colors.length];
}

export const GuestAvatar = memo(function GuestAvatar({ name, phone, size = "md", className }: GuestAvatarProps) {
  const seed = name || phone || "?";
  const initial = seed[0]?.toUpperCase() ?? "?";
  const color = avatarColor(seed);

  return (
    <div className={cn(
      "rounded-full bg-gradient-to-br flex items-center justify-center text-white font-bold flex-shrink-0",
      color, SIZE[size], className
    )}>
      {initial}
    </div>
  );
});
