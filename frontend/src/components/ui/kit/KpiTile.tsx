// One headline number as a compact, tappable tile (owner, 28 Nov 2026). Two rows only: a small icon + label on top with any
// side facts (channel counts, a "missed" badge) in the top-right corner; the number below with its trend line on the right.
// The tile wears its domain's colour (leads green, calls indigo, bookings and money coral), the whole tile opens the list
// behind the number, and the number scales with the tile so it never spills on a narrow screen.
import type { ComponentType, ReactNode } from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { Lock } from "@/lib/icons";
import { Sparkline } from "./Sparkline";

export type KpiTone = "lead" | "call" | "book";

// Written out in full so Tailwind sees every class.
const TONE: Record<KpiTone, { card: string; ink: string }> = {
  lead: { card: "border-[var(--haip-dom-lead-bd)] bg-[var(--haip-dom-lead-bg)]", ink: "text-[var(--haip-dom-lead-ink)]" },
  call: { card: "border-[var(--haip-dom-call-bd)] bg-[var(--haip-dom-call-bg)]", ink: "text-[var(--haip-dom-call-ink)]" },
  book: { card: "border-[var(--haip-dom-book-bd)] bg-[var(--haip-dom-book-bg)]", ink: "text-[var(--haip-dom-book-ink)]" },
};

/** A small white pill for a side fact inside a tile: an icon and a count ("WhatsApp 1"). `label` is what a screen reader hears. */
export function TileFact({ label, children, tone = "plain" }: { label: string; children: ReactNode; tone?: "plain" | "danger" }) {
  return (
    <span aria-label={label} role="img"
      className={cn("inline-flex tabular-nums min-h-5 items-center gap-1 rounded-full px-1.5 text-[11px] font-bold",
        tone === "danger" ? "bg-[var(--haip-status-danger-bg)] text-[var(--haip-status-danger-fg)]" : "bg-[var(--haip-card)] text-[var(--haip-fg)]")}>
      {children}
    </span>
  );
}

export function KpiTile({ tone, icon: Icon, label, value, facts, trend, trendLabel, href, locked, className }: {
  tone: KpiTone;
  icon: ComponentType<{ size?: number; className?: string }>;
  label: string;
  value: ReactNode;
  /** Side facts for the top-right corner (`TileFact`s). */
  facts?: ReactNode;
  /** The last days of this number, oldest first; drawn as the trend line. Leave out when there is no history to show. */
  trend?: number[] | null;
  /** Read by screen readers in place of the line. */
  trendLabel?: string;
  href: string;
  /** The viewer's role may not see this number: say so, never show 0. */
  locked?: boolean;
  className?: string;
}) {
  const t = TONE[tone];
  return (
    <Link href={href} aria-label={locked ? `${label}: hidden for your role` : undefined}
      className={cn("@container flex min-w-0 flex-col gap-1 rounded-[14px] border px-3 py-2 text-[var(--haip-fg)] transition-transform duration-150 active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50",
        t.card, className)}>
      <span className="flex min-h-[22px] items-center justify-between gap-1.5">
        <span className={cn("flex min-w-0 items-center gap-1.5 text-[12px] font-bold", t.ink)}>
          <Icon size={14} className="shrink-0" aria-hidden />
          <span className="truncate">{label}</span>
        </span>
        {/* side facts give way before the label does: a 144px tile (320px phone) shows the full label instead */}
        {facts && <span className="hidden shrink-0 gap-1 @[9.5rem]:flex">{facts}</span>}
      </span>
      <span className="flex flex-wrap items-center justify-between gap-x-2 gap-y-0.5">
        <span className={cn("flex items-center tabular-nums gap-1.5 whitespace-nowrap font-[family-name:var(--font-display)] font-bold leading-none tracking-[-0.01em]",
          locked ? "text-[14px] text-[var(--haip-fg-subtle)]" : "text-[clamp(20px,14cqi,32px)]")}>
          {locked && <Lock size={13} aria-hidden />}{locked ? "Hidden" : value}
        </span>
        {!locked && trend && trend.length > 1 && (
          <Sparkline values={trend} label={trendLabel ?? `${label}, recent days: ${trend.join(", ")}`} className={cn("ml-auto", t.ink)} />
        )}
      </span>
    </Link>
  );
}
