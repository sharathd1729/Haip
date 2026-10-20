import { memo, useState } from "react";
import { cn } from "@/lib/utils";
import { avatarInitials, avatarTintClass } from "@/lib/avatarTint";

interface GuestAvatarProps {
  name?: string | null;
  phone?: string | null;
  size?: "sm" | "md" | "lg";
  className?: string;
  /** Real photo URL, when one exists. Falls back to the initials circle
   * on a missing/broken image (guests have no self-service upload, so
   * this stays undefined for every guest today -- reserved for staff use
   * via UserAvatar's own real-photo support). */
  photoUrl?: string | null;
}

const SIZE = {
  sm: "w-7 h-7 text-xs",
  md: "w-9 h-9 text-sm",
  lg: "w-12 h-12 text-base",
};

export const GuestAvatar = memo(function GuestAvatar({ name, phone, size = "md", className, photoUrl }: GuestAvatarProps) {
  const seed = name || phone || "?";
  const initial = avatarInitials(seed);
  const color = avatarTintClass(seed);
  const [imgFailed, setImgFailed] = useState(false);

  if (photoUrl && !imgFailed) {
    return (
      <img
        src={photoUrl}
        alt={name || phone || "Avatar"}
        onError={() => setImgFailed(true)}
        className={cn("rounded-full object-cover flex-shrink-0", SIZE[size], className)}
      />
    );
  }

  return (
    <div className={cn(
      "rounded-full flex items-center justify-center font-bold tracking-[-0.02em] flex-shrink-0",
      color, SIZE[size], className
    )}>
      {initial}
    </div>
  );
});
