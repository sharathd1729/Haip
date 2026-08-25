/**
 * EmptyState — centered icon + heading + subtext + optional CTA.
 *
 * Design spec:
 *   Icon: 40px, muted color
 *   Heading: text-sm font-medium
 *   Subtext: text-xs text-muted-foreground
 *   CTA button: rounded-lg, bg-primary
 *   Never show blank white space — always pass at least a title.
 */
import { cn } from "@/lib/utils";
import Link from "next/link";
import { type ReactNode } from "react";
import { SlidersHorizontal, ExternalLink } from "@/lib/icons";

interface EmptyStateCTAProps {
  label: string;
  href?: string;
  onClick?: () => void;
  variant?: "primary" | "secondary";
}

interface EmptyStateProps {
  /** Lucide icon element — rendered at ~20px inside a 40px muted container */
  icon?: ReactNode;
  title: string;
  description?: string;
  cta?: EmptyStateCTAProps;
  secondaryCta?: EmptyStateCTAProps;
  learnMoreUrl?: string;
  learnMoreLabel?: string;
  /** Filtered-zero variant — shows "clear filter" instead of primary CTA */
  isFiltered?: boolean;
  onClearFilter?: () => void;
  className?: string;
}

function CTAButton({ cta, isPrimary }: { cta: EmptyStateCTAProps; isPrimary: boolean }) {
  const base = "inline-flex items-center gap-2 text-xs font-semibold rounded-lg px-4 py-2 transition-colors duration-150";
  const cls = cn(
    base,
    isPrimary
      ? "text-primary-foreground hover:opacity-90"
      : "border border-border hover:bg-muted text-foreground",
  );
  const style = isPrimary ? { background: "var(--primary)", color: "var(--primary-foreground)" } : undefined;

  if (cta.href) {
    return <Link href={cta.href} className={cls} style={style}>{cta.label}</Link>;
  }
  return <button onClick={cta.onClick} className={cls} style={style}>{cta.label}</button>;
}

export function EmptyState({
  icon,
  title,
  description,
  cta,
  secondaryCta,
  learnMoreUrl,
  learnMoreLabel = "Watch 2-min walkthrough",
  isFiltered = false,
  onClearFilter,
  className,
}: EmptyStateProps) {
  if (isFiltered) {
    return (
      <div className={cn("flex flex-col items-center justify-center text-center py-16 px-8", className)}>
        {/* Icon container — 40px */}
        <div
          className="w-10 h-10 rounded-xl flex items-center justify-center mb-4"
          style={{ background: "var(--muted)", color: "var(--haip-fg-subtle)" }}
        >
          <SlidersHorizontal size={18} />
        </div>
        <p className="text-sm font-medium mb-1" style={{ color: "var(--haip-fg)" }}>{title}</p>
        {description && (
          <p className="text-xs mb-5 max-w-xs leading-relaxed" style={{ color: "var(--haip-fg-subtle)" }}>
            {description}
          </p>
        )}
        {onClearFilter && (
          <button
            onClick={onClearFilter}
            className="text-xs font-semibold underline underline-offset-4 transition-colors duration-150"
            style={{ color: "var(--primary)" }}
          >
            Clear filter
          </button>
        )}
      </div>
    );
  }

  return (
    <div className={cn("flex flex-col items-center justify-center text-center py-16 px-8", className)}>
      {/* Icon container — 40px */}
      {icon && (
        <div
          className="w-10 h-10 rounded-xl flex items-center justify-center mb-4"
          style={{ background: "var(--muted)", color: "var(--haip-fg-subtle)" }}
        >
          {icon}
        </div>
      )}

      <p className="text-sm font-medium mb-1" style={{ color: "var(--haip-fg)" }}>{title}</p>

      {description && (
        <p className="text-xs mb-6 max-w-xs leading-relaxed" style={{ color: "var(--haip-fg-subtle)" }}>
          {description}
        </p>
      )}

      {(cta || secondaryCta) && (
        <div className="flex items-center gap-3 flex-wrap justify-center">
          {cta && <CTAButton cta={cta} isPrimary />}
          {secondaryCta && <CTAButton cta={secondaryCta} isPrimary={false} />}
        </div>
      )}

      {learnMoreUrl && (
        <a
          href={learnMoreUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 text-xs font-medium mt-5 transition-colors duration-150"
          style={{ color: "var(--primary)" }}
        >
          <ExternalLink size={12} />
          {learnMoreLabel}
        </a>
      )}
    </div>
  );
}
