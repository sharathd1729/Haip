"use client";
// Small shared pieces of the owner dashboard (layout A). Presentation only. Bars are SVG (width as an attribute), so no inline
// styles; colours come from tokens.
import type { ReactNode } from "react";
import Link from "next/link";
import { Lock } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { Card, CardBody, CardHeader } from "@/components/ui/kit";
import { deltaText } from "./owner";
import type { Change } from "./types";

/** A card with its title and, always, the period it covers. */
export function Block({ title, period, actions, children, className, id }: {
  title: ReactNode; period: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; id?: string;
}) {
  return (
    <Card className={cn("min-w-0", className)} aria-labelledby={id}>
      <CardHeader title={<span id={id}>{title}</span>} description={period} actions={actions} />
      <CardBody>{children}</CardBody>
    </Card>
  );
}

const FILL = { primary: "fill-primary", soft: "fill-primary/40", series2: "fill-[var(--haip-series-2)]", accent: "fill-[var(--haip-accent)]" } as const;

/** A horizontal bar: `parts` are percentages of the full width, stacked left to right; `marker` draws a thin line at that %. */
export function Meter({ parts, marker, label, className }: {
  parts: { pct: number; tone: keyof typeof FILL }[]; marker?: number; label: string; className?: string;
}) {
  let x = 0;
  return (
    <svg role="img" aria-label={label} className={cn("h-2.5 w-full overflow-visible rounded-full", className)} preserveAspectRatio="none">
      <rect x="0" y="0" width="100%" height="100%" rx="5" className="fill-[var(--haip-status-neutral-bg)]" />
      {parts.map((p, i) => {
        const w = Math.max(0, Math.min(100 - x, p.pct));
        const r = <rect key={i} x={`${x}%`} y="0" width={`${w}%`} height="100%" rx={i === 0 ? 5 : 0} className={FILL[p.tone]} />;
        x += w;
        return r;
      })}
      {marker != null && <line x1={`${marker}%`} x2={`${marker}%`} y1="-3" y2="13" strokeWidth="2" className="stroke-[var(--haip-fg)]" />}
    </svg>
  );
}

/** The "vs previous period" line under a KPI. Says "nothing to compare with" against an empty baseline (never -100%). */
export function Delta({ change, previous, money }: { change: Change | null | undefined; previous: number | null | undefined; money?: boolean }) {
  const d = deltaText(change, previous, money);
  return (
    <span className={cn("tabular-nums", d.tone === "up" && "font-semibold text-[var(--haip-status-success-fg)]",
      d.tone === "down" && "font-semibold text-[var(--haip-status-danger-fg)]")}>{d.text}</span>
  );
}

export function Hidden({ what }: { what: string }) {
  return (
    <p className="flex items-start gap-2 rounded-lg bg-[var(--haip-surface)] px-3 py-3 text-[13px] text-[var(--haip-fg-2)]" role="note">
      <Lock size={15} className="mt-0.5 shrink-0 text-[var(--haip-icon-neutral)]" aria-hidden />
      <span>{what} are hidden for your role. An owner can grant access under Settings, Permissions.</span>
    </p>
  );
}

export function OpenLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link href={href} className="inline-flex min-h-11 items-center gap-1 text-[13px] font-semibold text-primary hover:underline lg:min-h-0">
      {children} <span aria-hidden>→</span>
    </Link>
  );
}

/** A labelled horizontal bar row (label | bar | number) for the small charts. */
export function BarRow({ label, value, max, tone = "primary" }: { label: ReactNode; value: number; max: number; tone?: keyof typeof FILL }) {
  return (
    <div className="grid grid-cols-[6.5rem_minmax(0,1fr)_2.5rem] items-center gap-2.5 text-[13px]">
      <span className="truncate text-[var(--haip-fg-2)]">{label}</span>
      <Meter parts={[{ pct: max ? (value / max) * 100 : 0, tone }]} label={`${value}`} />
      <span className="text-right font-semibold tabular-nums text-[var(--haip-fg)]">{value}</span>
    </div>
  );
}
