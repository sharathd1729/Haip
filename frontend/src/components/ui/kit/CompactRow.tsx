"use client";
// Phone list rows (mobile-first plan, 24 Oct 2026): 6-8 people per screen instead of 1-2 big cards. One row = avatar, who,
// one line of why, a coloured "how late" on the right, then at most two 44px actions within thumb reach.
import Link from "next/link";
import type { ComponentType, MouseEvent, ReactNode } from "react";
import { cn } from "@/lib/utils";
import type { Tone } from "@/components/ui/page";

// Written out in full so Tailwind sees every class. Text-only tones for the right-hand "how late" line.
const META_TONE: Record<Tone, string> = {
  neutral: "text-[var(--haip-fg-subtle)]",
  info: "text-[var(--haip-status-info-fg)]",
  success: "text-[var(--haip-status-success-fg)]",
  warning: "text-[var(--haip-status-warning-fg)]",
  danger: "text-[var(--haip-status-danger-fg)]",
  brand: "text-primary",
  highlight: "text-[var(--haip-accent-ink)]",
};

/** The white list a set of rows sits in: one card, hairlines between rows. */
export function RowList({ children, className, label }: { children: ReactNode; className?: string; label?: string }) {
  return <ul aria-label={label} className={cn("haip-card divide-y divide-[var(--haip-border)] overflow-hidden", className)}>{children}</ul>;
}

/** One person / booking / chat on a phone. The body is a link (`href`) or a button (`onClick`); `actions` sit beside it, never
 *  inside it (a button cannot live inside a link). `meta` is the right-hand fact, coloured by `metaTone` (severity). */
export function CompactRow({
  avatar, title, subtitle, extra, meta, metaTone = "neutral", metaSub, actions, href, onClick, selected, label, className,
}: {
  avatar?: ReactNode;
  title: ReactNode;
  /** One line, truncated: why this row needs you. */
  subtitle?: ReactNode;
  /** An optional third line: small pills (stage, owner, "AI draft"). */
  extra?: ReactNode;
  meta?: ReactNode;
  metaTone?: Tone;
  /** A small grey line under `meta` (a time, "paid"). */
  metaSub?: ReactNode;
  actions?: ReactNode;
  href?: string;
  onClick?: () => void;
  selected?: boolean;
  /** Accessible name for the body when the title alone is not enough. */
  label?: string;
  className?: string;
}) {
  // With actions on the right there is no room for a meta column too: the "how late" moves onto the third line, as in the
  // approved mockup, so the why-line keeps its width.
  const metaInline = !!actions && !!meta;
  const body = (
    <>
      {avatar && <span className="shrink-0">{avatar}</span>}
      <span className="grid min-w-0 flex-1 gap-0.5">
        <span className="truncate text-[14.5px] font-semibold leading-tight text-[var(--haip-fg)]">{title}</span>
        {subtitle && <span className="truncate text-[13px] leading-snug text-[var(--haip-fg-2)]">{subtitle}</span>}
        {(extra || metaInline) && (
          <span className="flex min-w-0 flex-wrap items-center gap-1 pt-0.5">
            {metaInline && <span className={cn("mr-0.5 text-[12px] font-bold tabular-nums", META_TONE[metaTone])}>{meta}</span>}
            {extra}
          </span>
        )}
      </span>
      {!metaInline && (meta || metaSub) && (
        <span className="grid shrink-0 justify-items-end gap-0.5 text-right">
          {meta && <span className={cn("text-[12.5px] font-bold tabular-nums leading-tight", META_TONE[metaTone])}>{meta}</span>}
          {metaSub && <span className="text-[11.5px] tabular-nums leading-tight text-[var(--haip-fg-subtle)]">{metaSub}</span>}
        </span>
      )}
    </>
  );
  const bodyCls = cn(
    "flex min-h-[60px] min-w-0 flex-1 items-center gap-3 py-2 pl-3 text-left outline-none transition-colors",
    "active:bg-[var(--hover-bg)] focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary",
    !actions && "pr-3",
  );
  return (
    <li className={cn("flex items-center", selected && "bg-[var(--haip-primary-tint)]", className)}>
      {href ? (
        <Link href={href} aria-label={label} className={bodyCls}>{body}</Link>
      ) : onClick ? (
        <button type="button" onClick={onClick} aria-label={label} className={bodyCls}>{body}</button>
      ) : (
        <div className={bodyCls}>{body}</div>
      )}
      {actions && <span className="flex shrink-0 items-center gap-1.5 py-2 pl-2 pr-3">{actions}</span>}
    </li>
  );
}

/** A 44px action on a row: `primary` is the one thing to do (terracotta action colour), `quiet` everything else. Pass `href`
 *  for a link, otherwise it is a button. The label is the accessible name and the tooltip; the icon carries it visually. */
export function RowAction({ icon: Icon, label, onClick, href, primary, disabled, className }: {
  icon: ComponentType<{ size?: number; className?: string }>;
  label: string;
  onClick?: () => void;
  href?: string;
  primary?: boolean;
  disabled?: boolean;
  className?: string;
}) {
  const cls = cn(
    "inline-flex size-11 shrink-0 items-center justify-center rounded-xl border transition-transform active:scale-95 disabled:opacity-50",
    "outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2",
    primary
      ? "border-transparent bg-[var(--haip-action)] text-[var(--haip-on-action)]"
      : "border-[var(--haip-border)] bg-[var(--haip-surface)] text-primary",
    className,
  );
  if (href) return <Link href={href} aria-label={label} title={label} className={cls}><Icon size={19} /></Link>;
  return (
    <button type="button" aria-label={label} title={label} disabled={disabled} className={cls}
      onClick={(e: MouseEvent) => { e.stopPropagation(); onClick?.(); }}>
      <Icon size={19} />
    </button>
  );
}

/** Small pill for the third line of a row. Same tones as StatusPill, a size smaller. */
export function RowTag({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className={cn("inline-flex items-center whitespace-nowrap rounded-full px-2 py-px text-[11.5px] font-semibold leading-4", TAG_TONE[tone])}>
      {children}
    </span>
  );
}

const TAG_TONE: Record<Tone, string> = {
  neutral: "bg-[var(--haip-status-neutral-bg)] text-[var(--haip-status-neutral-fg)]",
  info: "bg-[var(--haip-status-info-bg)] text-[var(--haip-status-info-fg)]",
  success: "bg-[var(--haip-status-success-bg)] text-[var(--haip-status-success-fg)]",
  warning: "bg-[var(--haip-status-warning-bg)] text-[var(--haip-status-warning-fg)]",
  danger: "bg-[var(--haip-status-danger-bg)] text-[var(--haip-status-danger-fg)]",
  brand: "bg-[var(--haip-primary-tint)] text-primary",
  highlight: "bg-[var(--haip-accent-light)] text-[var(--haip-accent-ink)]",
};

/** Section title above a RowList: "Call now · 5", with an optional link on the right. */
export function RowSection({ title, count, action, children, className }: {
  title: ReactNode; count?: number; action?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <section className={cn("grid gap-1.5", className)}>
      <div className="flex items-baseline justify-between gap-2 px-0.5">
        <h2 className="font-[family-name:var(--font-display)] text-[15px] font-semibold text-[var(--haip-fg)]">
          {title}{count != null && <span className="num ml-1.5 text-[13px] font-semibold text-[var(--haip-fg-subtle)]">{count}</span>}
        </h2>
        {action}
      </div>
      {children}
    </section>
  );
}
