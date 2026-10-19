"use client";
// "Calendar clashes" on My day: tasks the calendar sync raised (a double booking, an event that names no vehicle, more bookings
// than vehicles). Work-queue kind `clash`. They are about the calendar, not a person, so they sit apart from the people lists;
// each row opens the calendar on that day. The sync closes a clash task itself once the clash is gone.
import Link from "next/link";
import { Card, StatusPill } from "@/components/ui/kit";

export interface ClashItem {
  kind: string; title: string; detail: string; action: string; href: string;
  facts: string[]; severity: string;
}

export function CalendarClashes({ items }: { items: ClashItem[] }) {
  if (items.length === 0) return null;
  return (
    <section className="space-y-2" aria-labelledby="calendar-clashes-title">
      <h2 id="calendar-clashes-title" className="flex items-baseline gap-2 text-[13px] font-bold uppercase tracking-wide text-[var(--haip-fg-2)]">
        Calendar clashes
        <span className="rounded-full bg-[var(--haip-surface)] px-2 py-0.5 text-[11px] font-semibold tabular-nums text-[var(--haip-fg-subtle)]">{items.length}</span>
        <span className="text-[11.5px] font-normal normal-case tracking-normal text-[var(--haip-fg-subtle)]">sort out on the calendar</span>
      </h2>
      <Card className="overflow-hidden">
        {items.map((item, i) => (
          <div key={`${item.title}-${i}`} className="flex items-center border-t border-[var(--haip-border)] first:border-t-0 shadow-[inset_3px_0_0_var(--haip-status-danger-fg)]">
            <Link href={item.href}
              className="flex min-h-16 min-w-0 flex-1 items-center gap-3 px-4 py-3 outline-none transition-colors hover:bg-[var(--haip-surface)] focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary">
              <div className="min-w-0 flex-1">
                <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5">
                  <span className="text-sm font-bold text-[var(--haip-fg)] [overflow-wrap:anywhere]">{item.title}</span>
                  <StatusPill tone="danger">{item.severity === "critical" ? "Soon" : "Needs a decision"}</StatusPill>
                </span>
                <p className="mt-0.5 text-xs text-[var(--haip-fg-subtle)]">{item.detail}</p>
                {item.facts.length > 0 && (
                  <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11.5px]">
                    {item.facts.map(f => <span key={f} className="rounded bg-[var(--haip-surface)] px-1.5 py-0.5 font-medium text-[var(--haip-fg-2)]">{f}</span>)}
                  </p>
                )}
              </div>
              <span aria-hidden className="inline-flex min-h-11 items-center justify-center whitespace-nowrap rounded-lg bg-primary px-4 text-[13px] font-bold text-primary-foreground">
                {item.action}
              </span>
            </Link>
          </div>
        ))}
      </Card>
    </section>
  );
}
