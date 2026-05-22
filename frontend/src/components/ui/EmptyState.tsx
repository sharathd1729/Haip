/**
 * X7 — Reusable EmptyState component
 *
 * Use for every list / table view that can be empty.
 * Distinguishes two cases:
 *  - no-data: primary CTA, optional Loom embed
 *  - filtered-zero: "clear filter" CTA
 */

import { cn } from "@/lib/utils";
import Link from "next/link";
import { type ReactNode } from "react";
import { SlidersHorizontal, ExternalLink } from "lucide-react";

interface EmptyStateCTAProps {
  label: string;
  href?: string;
  onClick?: () => void;
  variant?: "primary" | "secondary";
}

interface EmptyStateProps {
  /** Lucide icon element (sized 24–32px) */
  icon?: ReactNode;
  title: string;
  description?: string;
  /** Primary action button */
  cta?: EmptyStateCTAProps;
  /** Secondary action — e.g. "import" or "view docs" */
  secondaryCta?: EmptyStateCTAProps;
  /** Loom video URL — renders as an embed or link */
  learnMoreUrl?: string;
  learnMoreLabel?: string;
  /** If true, show "this is a filtered view" variant */
  isFiltered?: boolean;
  onClearFilter?: () => void;
  className?: string;
}

function CTAButton({ cta, isPrimary }: { cta: EmptyStateCTAProps; isPrimary: boolean }) {
  const cls = cn(
    "inline-flex items-center gap-2 text-sm font-semibold rounded-xl px-5 py-2.5 transition-colors",
    isPrimary
      ? "bg-indigo-500 hover:bg-indigo-600 text-white shadow-sm shadow-indigo-200"
      : "bg-white border border-gray-200 hover:bg-gray-50 text-gray-700"
  );
  if (cta.href) {
    return <Link href={cta.href} className={cls}>{cta.label}</Link>;
  }
  return (
    <button onClick={cta.onClick} className={cls}>{cta.label}</button>
  );
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
        <div className="w-12 h-12 rounded-2xl bg-gray-100 flex items-center justify-center mb-4">
          <SlidersHorizontal size={22} className="text-gray-400" />
        </div>
        <p className="text-gray-800 font-semibold text-sm mb-1">{title}</p>
        {description && <p className="text-gray-500 text-sm mb-5 max-w-xs">{description}</p>}
        {onClearFilter && (
          <button
            onClick={onClearFilter}
            className="text-sm font-semibold text-indigo-600 hover:text-indigo-700 underline underline-offset-4"
          >
            Clear filter
          </button>
        )}
      </div>
    );
  }

  return (
    <div className={cn("flex flex-col items-center justify-center text-center py-16 px-8", className)}>
      {icon && (
        <div className="w-14 h-14 rounded-2xl bg-gray-100 flex items-center justify-center mb-5 text-gray-400">
          {icon}
        </div>
      )}
      <p className="text-gray-900 font-bold text-base mb-1.5">{title}</p>
      {description && (
        <p className="text-gray-500 text-sm mb-6 max-w-xs leading-relaxed">{description}</p>
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
          className="inline-flex items-center gap-1.5 text-xs text-indigo-600 hover:text-indigo-700 mt-5 font-medium"
        >
          <ExternalLink size={12} />
          {learnMoreLabel}
        </a>
      )}
    </div>
  );
}
