import { memo, useState } from "react";
import { cn } from "@/lib/utils";
import { avatarInitials, avatarTintClass } from "@/lib/avatarTint";

interface UserAvatarProps {
  name?: string | null;
  /** Presigned avatar_url from UserOut, when the user has one. Falls back
   * to the initials circle on a missing/broken image. */
  photoUrl?: string | null;
  size?: "sm" | "md" | "lg" | "xl";
  className?: string;
}

const SIZE = {
  sm: "w-7 h-7 text-xs",
  md: "w-9 h-9 text-sm",
  lg: "w-12 h-12 text-base",
  xl: "w-20 h-20 text-2xl",
};

export const UserAvatar = memo(function UserAvatar({ name, photoUrl, size = "md", className }: UserAvatarProps) {
  const seed = name || "?";
  const initial = avatarInitials(seed);
  const color = avatarTintClass(seed);
  const [imgFailed, setImgFailed] = useState(false);

  if (photoUrl && !imgFailed) {
    return (
      <img
        src={photoUrl}
        alt={name || "User"}
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
