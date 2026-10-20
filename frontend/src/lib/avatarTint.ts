// Hospitality Hybrid person avatars: a soft tint with ink-coloured initials, the tint picked by a stable hash of the seed
// (name, else phone) so one person always gets the same colour. Tokens live in globals.css (--haip-avatar-N-bg/-fg).
// Class names are written out in full so Tailwind can see them.
const AVATAR_CLASSES = [
  "bg-[var(--haip-avatar-1-bg)] text-[var(--haip-avatar-1-fg)]",
  "bg-[var(--haip-avatar-2-bg)] text-[var(--haip-avatar-2-fg)]",
  "bg-[var(--haip-avatar-3-bg)] text-[var(--haip-avatar-3-fg)]",
  "bg-[var(--haip-avatar-4-bg)] text-[var(--haip-avatar-4-fg)]",
  "bg-[var(--haip-avatar-5-bg)] text-[var(--haip-avatar-5-fg)]",
];

export function avatarTintClass(seed: string): string {
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0;
  return AVATAR_CLASSES[h % AVATAR_CLASSES.length];
}

/** Up to two initials from a name ("Priya Nair" -> "PN"); a phone number gives its first digit, nothing gives "?". */
export function avatarInitials(seed: string): string {
  const words = seed.trim().split(/\s+/).filter(w => /^\p{L}/u.test(w));
  if (words.length >= 2) return (words[0][0] + words[words.length - 1][0]).toUpperCase();
  if (words.length === 1) return words[0][0].toUpperCase();
  return seed.replace(/[^\p{L}\p{N}]/gu, "")[0]?.toUpperCase() ?? "?";
}
