"use client";
// "Needs attention": the six things that need a person now (owner dashboard, layout A). Five are read from the shared work queue
// (kinds no_reply / callback, flags not_called / open_lead / at_risk), the sixth is bookings still owing money. Each card: how many,
// why, the first three names with how long they have waited, and an Open link to the full list. People without a phone number
// are never here (D-22).
import Link from "next/link";
import { CheckCircle2 } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { Card } from "@/components/ui/kit";
import { ageText, lakh, type AttentionCard, type AttentionPerson, type Severity } from "./owner";

const EDGE: Record<Severity, string> = {
  fresh: "", stale: "",
  late: "shadow-[inset_3px_0_0_var(--haip-status-warning-fg)]",
  urgent: "shadow-[inset_3px_0_0_var(--haip-status-danger-fg)]",
  critical: "shadow-[inset_3px_0_0_var(--haip-status-danger-fg)]",
};

function personLine(card: AttentionCard, p: AttentionPerson): string {
  if (card.key === "owing") {
    const amount = p.amount != null ? lakh(p.amount) : null;
    const due = p.overdue ? "overdue" : p.due_date ? `due ${new Date(`${p.due_date}T12:00:00+05:30`).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}` : "no schedule";
    return [amount, due].filter(Boolean).join(" · ");
  }
  const age = ageText(p.since);
  const fact = p.facts?.[0];
  return [fact, age && (card.key === "followups" ? `due ${age} ago` : age)].filter(Boolean).join(" · ");
}

function CardBlock({ card }: { card: AttentionCard }) {
  if (card.restricted) {
    return (
      <Card className="flex min-h-[176px] flex-col gap-2 px-4 py-4">
        <span className="text-[14px] font-semibold text-[var(--haip-fg)]">{card.title}</span>
        <span className="text-[13px] text-[var(--haip-fg-subtle)]">Hidden for your role: it needs the bookings permission.</span>
      </Card>
    );
  }
  const n = card.count ?? 0;
  const owing = card.key === "owing";
  const people = card.people ?? [];
  const headline = owing ? (card.amount != null ? lakh(card.amount) : String(n)) : String(n);
  return (
    <Card className={cn("flex min-h-[176px] min-w-0 flex-col gap-2 px-4 py-4", n > 0 && EDGE[card.severity ?? "fresh"])}>
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="min-w-0 text-[14.5px] font-semibold leading-tight text-[var(--haip-fg)]">{card.title}</h3>
        <span className={cn("shrink-0 font-[family-name:var(--font-display)] text-[24px] font-semibold leading-none tabular-nums",
          n ? "text-[var(--haip-fg)]" : "text-[var(--haip-fg-subtle)]")}>{headline}</span>
      </div>
      <p className="text-[12.5px] leading-snug text-[var(--haip-fg-subtle)]">
        {card.reason}{owing && n > 0 ? ` · ${n} booking${n === 1 ? "" : "s"}` : ""}
      </p>
      {n === 0 ? (
        <p className="mt-auto flex items-center gap-1.5 text-[13px] text-[var(--haip-fg-2)]">
          <CheckCircle2 size={15} className="text-[var(--haip-status-success-fg)]" aria-hidden />All clear
        </p>
      ) : (
        <ul className="space-y-1">
          {people.map((p, i) => (
            <li key={`${p.name}-${i}`} className="flex min-w-0 items-baseline justify-between gap-2 text-[13px]">
              <span className="min-w-0 truncate font-medium text-[var(--haip-fg)]">{p.name}</span>
              <span className="shrink-0 tabular-nums text-[var(--haip-fg-subtle)]">{personLine(card, p)}</span>
            </li>
          ))}
        </ul>
      )}
      {n > 0 && card.href && (
        <Link href={card.href} className="mt-auto inline-flex min-h-11 items-center gap-1 self-start text-[13px] font-semibold text-primary hover:underline lg:min-h-8">
          {n > people.length && !owing ? `See all ${n}` : "Open"} <span aria-hidden>→</span>
        </Link>
      )}
    </Card>
  );
}

export function NeedsAttention({ cards }: { cards: AttentionCard[] }) {
  return (
    <section aria-labelledby="needs-attention-title" id="needs-attention">
      <div className="mb-2.5 flex flex-wrap items-baseline justify-between gap-x-3 px-0.5">
        <h2 id="needs-attention-title" className="font-[family-name:var(--font-display)] text-[17px] font-semibold tracking-[-0.01em] text-[var(--haip-fg)]">Needs attention</h2>
        <span className="text-[12.5px] text-[var(--haip-fg-subtle)]">right now · people with a phone number</span>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {cards.map(c => <CardBlock key={c.key} card={c} />)}
      </div>
    </section>
  );
}
