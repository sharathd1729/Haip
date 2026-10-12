"use client";
// "Needs you now": only items that exist, from the shared work queue and booking money rules, plus integrations that
// are stale or failing. Calm by default — an empty strip says so instead of showing a row of zeros.
import Link from "next/link";
import { CheckCircle2, ChevronRight } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { ago, num, type BusinessOverview } from "./types";

const RED_KEYS = new Set(["payment_overdue", "missed_calls"]);

export function AttentionStrip({ data }: { data: BusinessOverview }) {
  const items = data.attention.filter(a => a.count > 0);
  const stale = data.stale_integrations;
  const quiet = items.length === 0 && stale.length === 0;

  return (
    <section aria-label="Needs attention" className="haip-card px-5 py-3.5 sm:px-6">
      {quiet ? (
        <p className="flex items-center gap-2 text-[13px] text-[var(--haip-fg-2)]">
          <CheckCircle2 size={16} className="text-[var(--haip-status-success-fg)]" aria-hidden />
          Nothing is waiting on your team right now, and every connected channel is syncing.
        </p>
      ) : (
        <ul className="flex flex-col divide-y divide-[var(--haip-border)] sm:flex-row sm:flex-wrap sm:divide-y-0 sm:gap-x-8 sm:gap-y-2">
          {items.map(a => (
            <li key={a.key} className="min-w-0">
              <Link href={a.href} className="group flex min-h-11 items-center gap-2.5 py-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 rounded">
                <span className={cn("min-w-[1.5rem] text-right font-[family-name:var(--font-display)] text-[22px] font-semibold leading-none tabular-nums",
                  RED_KEYS.has(a.key) ? "text-[var(--haip-status-danger-fg)]" : "text-[var(--haip-status-warning-fg)]")}>{num(a.count)}</span>
                <span className="text-[13px] text-[var(--haip-fg-2)] group-hover:text-[var(--haip-fg)]">
                  {a.label}
                  {a.oldest_at && <span className="ml-1.5 text-[11.5px] text-[var(--haip-fg-subtle)]">oldest {ago(a.oldest_at)}</span>}
                </span>
                <ChevronRight size={14} className="text-[var(--haip-icon-neutral)]" aria-hidden />
              </Link>
            </li>
          ))}
          {stale.map(s => (
            <li key={s.kind} className="min-w-0">
              <Link href={s.href} className="group flex min-h-11 items-center gap-2.5 py-1 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40">
                <span className={cn("size-2.5 shrink-0 rounded-full", s.status === "red" ? "bg-[var(--haip-red)]" : "bg-[var(--haip-amber)]")} aria-hidden />
                <span className="text-[13px] text-[var(--haip-fg-2)]">
                  <span className="font-semibold text-[var(--haip-fg)]">{s.label}</span>{" "}
                  {s.status === "red" ? "has stopped syncing" : "is behind on syncing"}
                  {s.last_sync && <span className="ml-1.5 text-[11.5px] text-[var(--haip-fg-subtle)]">last {ago(s.last_sync)} ago</span>}
                  <span className="sr-only">{s.status === "red" ? " (critical)" : " (warning)"}. Numbers that depend on it may be out of date.</span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
