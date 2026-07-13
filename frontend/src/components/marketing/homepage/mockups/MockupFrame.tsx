/**
 * Browser-window chrome wrapper shared by all product mockups.
 * Pure presentational — parent sections handle animation.
 */
export function MockupFrame({
  title,
  children,
  className = "",
}: {
  title: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`rounded-xl overflow-hidden ${className}`}
      style={{
        backgroundColor: "var(--home-card)",
        border: "1px solid var(--home-border)",
        boxShadow: "var(--home-shadow-lg)",
      }}
    >
      <div
        className="flex items-center gap-2 px-4 h-9 border-b"
        style={{ borderColor: "var(--home-border)", backgroundColor: "#F6F6F4" }}
      >
        <span className="flex gap-1.5" aria-hidden="true">
          <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: "#E4E4E0" }} />
          <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: "#E4E4E0" }} />
          <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: "#E4E4E0" }} />
        </span>
        <span
          className="text-[11px] font-medium mx-auto truncate"
          style={{ color: "var(--home-text-subtle)" }}
        >
          {title}
        </span>
      </div>
      {children}
    </div>
  );
}

/** Small channel/status chip used across mockups. */
export function Chip({
  label,
  tone = "neutral",
}: {
  label: string;
  tone?: "neutral" | "accent" | "success" | "warning";
}) {
  const tones: Record<string, { bg: string; fg: string }> = {
    neutral: { bg: "#F3F3F1", fg: "#666666" },
    accent: { bg: "rgba(11,107,94,0.08)", fg: "#0B6B5E" },
    success: { bg: "rgba(31,157,85,0.10)", fg: "#1F9D55" },
    warning: { bg: "rgba(217,119,6,0.10)", fg: "#D97706" },
  };
  const t = tones[tone];
  return (
    <span
      className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold whitespace-nowrap"
      style={{ backgroundColor: t.bg, color: t.fg }}
    >
      {label}
    </span>
  );
}
