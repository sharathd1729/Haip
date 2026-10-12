"use client";
// Small shared pieces of the Owner Command Center. Presentation only: every value arrives formatted-ready from the
// server response in ./types.ts.
import type { ReactNode } from "react";
import Link from "next/link";
import { ArrowDownRight, ArrowUpRight, Info, Lock } from "@/lib/icons";
import { cn } from "@/lib/utils";
import type { Change } from "./types";

/** "+12% vs previous" — only when the server found a baseline; nothing at all otherwise (never "+0%" / "-100%"). */
export function ChangePill({ change, goodWhen = "up", className }: { change: Change | null | undefined; goodWhen?: "up" | "down"; className?: string }) {
  if (!change) return null;
  const good = change.direction === "neutral" ? null : change.direction === goodWhen;
  const Arrow = change.direction === "down" ? ArrowDownRight : ArrowUpRight;
  return (
    <span className={cn(
      "inline-flex items-center gap-0.5 whitespace-nowrap text-xs font-semibold tabular-nums",
      good === null ? "text-[var(--haip-fg-subtle)]" : good ? "text-[var(--haip-status-success-fg)]" : "text-[var(--haip-status-danger-fg)]",
      className,
    )}>
      {change.direction !== "neutral" && <Arrow size={13} aria-hidden />}
      {change.pct > 0 ? "+" : ""}{change.pct}%
      <span className="sr-only"> compared with the previous period</span>
    </span>
  );
}

/** One label/value line of a definition list. `href` makes the whole line a drill-down. */
export function Row({ label, value, hint, href, tone, muted }: {
  label: ReactNode; value: ReactNode; hint?: ReactNode; href?: string; tone?: "warning" | "danger"; muted?: boolean;
}) {
  const body = (
    <>
      <dt className={cn("min-w-0 text-[13px]", muted ? "text-[var(--haip-fg-subtle)]" : "text-[var(--haip-fg-2)]")}>
        {label}
        {hint && <span className="block text-[11.5px] leading-snug text-[var(--haip-fg-subtle)]">{hint}</span>}
      </dt>
      <dd className={cn(
        "shrink-0 text-right text-[14px] font-semibold tabular-nums [overflow-wrap:anywhere]",
        tone === "warning" && "text-[var(--haip-status-warning-fg)]",
        tone === "danger" && "text-[var(--haip-status-danger-fg)]",
        !tone && (muted ? "text-[var(--haip-fg-subtle)]" : "text-[var(--haip-fg)]"),
      )}>{value}</dd>
    </>
  );
  const cls = "flex items-baseline justify-between gap-3 py-1.5";
  const tap = href ? " min-h-11 items-center lg:min-h-0" : "";
  return href
    ? <Link href={href} className={cn(cls + tap, "-mx-2 rounded-md px-2 transition-colors hover:bg-[var(--haip-surface)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40")}>{body}</Link>
    : <div className={cls}>{body}</div>;
}

/** Shown in place of a block the viewer may not read. Says why; never a zero. */
export function RestrictedNote({ what, permission }: { what: string; permission: string }) {
  return (
    <div className="flex items-start gap-2.5 rounded-lg bg-[var(--haip-surface)] px-3 py-3 text-[13px] text-[var(--haip-fg-2)]" role="note">
      <Lock size={15} className="mt-0.5 shrink-0 text-[var(--haip-icon-neutral)]" aria-hidden />
      <p>
        <span className="font-semibold text-[var(--haip-fg)]">{what} are hidden for your role.</span>{" "}
        They need the “{permission}” permission. An owner can grant it under Settings, Permissions.
      </p>
    </div>
  );
}

/** A figure HAIP cannot compute. The reason is on the page, not in a tooltip only. */
export function NotAvailable({ label, reason }: { label: string; reason: string }) {
  return (
    <div className="flex items-start gap-2 py-1.5 text-[12.5px] text-[var(--haip-fg-subtle)]">
      <Info size={14} className="mt-0.5 shrink-0" aria-hidden />
      <p><span className="font-semibold text-[var(--haip-fg-2)]">{label}: not available.</span> {reason}</p>
    </div>
  );
}

export function SectionTitle({ children, sub, actions }: { children: ReactNode; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-3 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
      <div className="min-w-0">
        <h2 className="font-[family-name:var(--font-display)] text-[17px] font-semibold tracking-tight text-[var(--haip-fg)]">{children}</h2>
        {sub && <p className="mt-0.5 text-xs text-[var(--haip-fg-subtle)]">{sub}</p>}
      </div>
      {actions}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="py-8 text-center text-[13px] text-[var(--haip-fg-subtle)]">{children}</p>;
}
