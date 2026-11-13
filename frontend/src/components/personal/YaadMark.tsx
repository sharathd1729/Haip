// Yaad's mark: a speech bubble holding two lines of notes (brand sheet, Klein theme). Colours come from the .yaad tokens.
export function YaadMark({ size = 28, className }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 96 96" aria-hidden="true" className={className}>
      <rect width="96" height="96" rx="24" fill="var(--y-brand)" />
      <path
        fill="var(--y-on-brand)"
        d="M34 22h28c9.94 0 18 8.06 18 18v6c0 9.94-8.06 18-18 18H42l-12 11.5c-1.3 1.24-3.4.32-3.4-1.46V63.1C20.94 60.4 16 53.8 16 46v-6c0-9.94 8.06-18 18-18z"
      />
      <rect x="31" y="35" width="34" height="6" rx="3" fill="var(--y-brand)" />
      {/* Second note line in the accent colour (--y-mark-line), chosen to read on the bubble. */}
      <rect x="31" y="47" width="21" height="6" rx="3" fill="var(--y-mark-line)" />
    </svg>
  );
}

export function YaadWordmark({ className }: { className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2 ${className ?? ""}`}>
      <YaadMark size={26} />
      <span className="text-[22px] font-bold leading-none tracking-[-0.05em] text-[var(--y-ink)]">yaad</span>
    </span>
  );
}
