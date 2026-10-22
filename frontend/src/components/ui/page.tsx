import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { PageIconTile, type RouteIcon } from "@/components/layout/PageIcon";

/** Title row for a dashboard page: an icon tile (main pages only), a display-face heading and one line of context on the
 *  left, actions on the right. The tile's icon comes from the route (components/layout/PageIcon.tsx, the same glyph the
 *  nav uses); pass `icon` to set one or `icon={false}` to drop it. On phones the header bar names the page, so globals.css
 *  hides the title there and the tile hides with it. */
export function PageHeader({
  title, subtitle, actions, icon, className,
}: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; icon?: RouteIcon | false; className?: string }) {
  return (
    <header className={cn("flex flex-wrap items-end gap-x-4 gap-y-3", className)}>
      <div className="flex min-w-0 flex-1 items-center gap-3.5">
        <PageIconTile icon={icon} />
        <div className="min-w-0 flex-1">
          <h1 className="haip-page-title">{title}</h1>
          {subtitle && <p className="mt-1 text-[14px] leading-snug text-[var(--haip-fg-muted)]">{subtitle}</p>}
        </div>
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

/** What to show when a list is empty: say what the list is for and offer the next step. */
export function EmptyState({
  title, hint, action, className,
}: { title: ReactNode; hint?: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <div className={cn("flex flex-col items-center justify-center gap-1.5 px-6 py-14 text-center", className)}>
      <p className="font-[family-name:var(--font-display)] text-[17px] font-semibold text-[var(--haip-fg)]">{title}</p>
      {hint && <p className="max-w-sm text-[13.5px] leading-relaxed text-[var(--haip-fg-subtle)]">{hint}</p>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}

// Written out in full (not built from a variable) so Tailwind can see every class.
const TONES = {
  neutral: "bg-[var(--haip-status-neutral-bg)] text-[var(--haip-status-neutral-fg)] border-[var(--haip-status-neutral-border)]",
  info:    "bg-[var(--haip-status-info-bg)] text-[var(--haip-status-info-fg)] border-[var(--haip-status-info-border)]",
  success: "bg-[var(--haip-status-success-bg)] text-[var(--haip-status-success-fg)] border-[var(--haip-status-success-border)]",
  warning: "bg-[var(--haip-status-warning-bg)] text-[var(--haip-status-warning-fg)] border-[var(--haip-status-warning-border)]",
  danger:  "bg-[var(--haip-status-danger-bg)] text-[var(--haip-status-danger-fg)] border-[var(--haip-status-danger-border)]",
  brand:   "bg-[var(--haip-primary-tint)] text-primary border-[color-mix(in_srgb,var(--primary)_22%,transparent)]",
  highlight: "bg-[var(--haip-accent-light)] text-[var(--haip-accent-ink)] border-[color-mix(in_srgb,var(--haip-accent)_35%,transparent)]",
} as const;

export type Tone = keyof typeof TONES;

/** A small label for a state (booking status, payment status, channel). The words carry the meaning;
 *  the colour only reinforces it, so it still reads for colour-blind users and in greyscale prints. */
export function StatusPill({ tone = "neutral", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-[12px] font-semibold leading-4", TONES[tone], className)}>
      {children}
    </span>
  );
}
