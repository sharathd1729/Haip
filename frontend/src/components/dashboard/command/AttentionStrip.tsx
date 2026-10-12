"use client";
// "Needs attention": the actionable list. Only items that exist, from the shared work queue, the booking money rules and
// integration health. Each row is a 44px touch target that opens the records. An empty list says so instead of showing zeros.
import Link from "next/link";
import { CheckCircle2, ChevronRight } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { ago, num, type BusinessOverview } from "./types";

const RED_KEYS = new Set(["payment_overdue", "missed_calls", "high_intent_risk"]);

export function AttentionStrip({ data }: { data: BusinessOverview }) {
  const items = data.attention.filter(a => a.count > 0);
  const stale = data.stale_integrations;
  const quiet = items.length === 0 && stale.length === 0;
  const risk = data.leads.high_intent_at_risk;

  return (
    <section id="needs-attention" aria-labelledby="attention-title" className="haip-card scroll-mt-4 px-4 py-3 sm:px-6">
      <h2 id="attention-title" className="mb-1 font-[family-name:var(--font-display)] text-[15px] font-semibold text-[var(--haip-fg)]">Needs attention</h2>
      {quiet ? (
        <p className="flex items-center gap-2 py-1.5 text-[13px] text-[var(--haip-fg-2)]">
          <CheckCircle2 size={16} className="shrink-0 text-[var(--haip-status-success-fg)]" aria-hidden />
          Nothing is waiting on your team right now, and every connected channel is syncing.
        </p>
      ) : (
        <ul className="divide-y divide-[var(--haip-border)] sm:grid sm:grid-cols-2 sm:gap-x-8 sm:divide-y-0 xl:grid-cols-3">
          {items.map(a => (
            <li key={a.key} className="min-w-0 sm:border-b sm:border-[var(--haip-border)] sm:last:border-b-0">
              <Link href={a.href} className="group flex min-h-11 items-center gap-3 py-1.5 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40">
                <span className={cn("min-w-[1.75rem] text-right font-[family-name:var(--font-display)] text-[22px] font-semibold leading-none tabular-nums",
                  RED_KEYS.has(a.key) ? "text-[var(--haip-status-danger-fg)]" : "text-[var(--haip-status-warning-fg)]")}>{num(a.count)}</span>
                <span className="min-w-0 flex-1 text-[13px] leading-snug text-[var(--haip-fg-2)] group-hover:text-[var(--haip-fg)]">
                  {a.label}
                  {a.oldest_at && <span className="ml-1.5 text-[11.5px] text-[var(--haip-fg-subtle)]">oldest {ago(a.oldest_at)}</span>}
                  {a.key === "high_intent_risk" && risk.items.length > 0 && (
                    <span className="block truncate text-[11.5px] text-[var(--haip-fg-subtle)]">{risk.items.map(i => `${i.name} (${i.reason})`).join(" · ")}</span>
                  )}
                </span>
                <ChevronRight size={14} className="shrink-0 text-[var(--haip-icon-neutral)]" aria-hidden />
              </Link>
            </li>
          ))}
          {stale.map(s => (
            <li key={s.kind} className="min-w-0 sm:border-b sm:border-[var(--haip-border)] sm:last:border-b-0">
              <Link href={s.href} className="group flex min-h-11 items-center gap-3 py-1.5 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40">
                <span className={cn("ml-2 mr-2.5 size-2.5 shrink-0 rounded-full", s.status === "red" ? "bg-[var(--haip-red)]" : "bg-[var(--haip-amber)]")} aria-hidden />
                <span className="min-w-0 flex-1 text-[13px] leading-snug text-[var(--haip-fg-2)]">
                  <span className="font-semibold text-[var(--haip-fg)]">{s.label}</span>{" "}
                  {s.status === "red" ? "has stopped syncing" : "is behind on syncing"}
                  {s.last_sync && <span className="ml-1.5 text-[11.5px] text-[var(--haip-fg-subtle)]">last {ago(s.last_sync)} ago</span>}
                  <span className="sr-only">{s.status === "red" ? " (critical)" : " (warning)"}. Numbers that depend on it may be out of date.</span>
                </span>
                <ChevronRight size={14} className="shrink-0 text-[var(--haip-icon-neutral)]" aria-hidden />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
