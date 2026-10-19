"use client";
// Pieces shared by the new-booking sections: the numbered section card (number -> tick or "!"), the problem / warning notes and
// the radio-style option row. Colours come from tokens only; 44px touch targets on phones.
import type { ReactNode } from "react";
import { Card, CardBody } from "@/components/ui/kit";
import { cn } from "@/lib/utils";
import type { SectionMark } from "./helpers";

export function SectionCard({ id, n, title, mark, summary, children }: {
  id: string; n: number; title: string; mark: SectionMark; summary?: ReactNode; children: ReactNode;
}) {
  return (
    <Card id={id} className="scroll-mt-4">
      <CardBody className="space-y-3 pt-4">
        <div className="flex items-center gap-2.5">
          <span data-testid={`mark-${id}`} aria-label={mark === "ok" ? "Done" : mark === "bad" ? "Needs fixing" : `Step ${n}`}
            className={cn("grid size-[26px] shrink-0 place-items-center rounded-full border text-[13px] font-bold",
              mark === "ok" && "border-primary bg-primary text-primary-foreground",
              mark === "bad" && "border-[var(--haip-status-danger-fg)] bg-[var(--haip-status-danger-bg)] text-[var(--haip-status-danger-fg)]",
              mark === "todo" && "border-[var(--haip-border-strong)] bg-[var(--haip-surface)] text-[var(--haip-fg-2)]")}>
            {mark === "ok" ? "✓" : mark === "bad" ? "!" : n}
          </span>
          <h2 className="min-w-0 flex-1 font-[family-name:var(--font-display)] text-[17px] font-semibold tracking-[-0.01em] text-[var(--haip-fg)]">{title}</h2>
          {summary && <span className="max-w-[50%] truncate text-right text-[13px] text-[var(--haip-fg-subtle)]">{summary}</span>}
        </div>
        {children}
      </CardBody>
    </Card>
  );
}

const NOTE = {
  bad: "bg-[var(--haip-status-danger-bg)] text-[var(--haip-status-danger-fg)]",
  warn: "bg-[var(--haip-status-warning-bg)] text-[var(--haip-status-warning-fg)]",
  ok: "bg-[var(--haip-status-success-bg)] text-[var(--haip-status-success-fg)]",
  info: "bg-[var(--haip-status-info-bg)] text-[var(--haip-status-info-fg)]",
} as const;

export function Note({ tone, children, actions }: { tone: keyof typeof NOTE; children: ReactNode; actions?: ReactNode }) {
  return (
    <div role={tone === "bad" ? "alert" : tone === "warn" ? "status" : undefined} className={cn("grid gap-2 rounded-xl px-3 py-2.5 text-[14px]", NOTE[tone])}>
      <div className="min-w-0">{children}</div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

/** One note for a list of messages: a sentence for one, a bullet list for several. */
export function Messages({ tone, items }: { tone: "bad" | "warn"; items: { message: string }[] }) {
  if (!items.length) return null;
  return (
    <Note tone={tone}>
      {items.length === 1 ? <span>{items[0].message}</span>
        : <ul className="grid list-disc gap-0.5 pl-4">{items.map(i => <li key={i.message}>{i.message}</li>)}</ul>}
    </Note>
  );
}

export function Opt({ on, onClick, title, sub, right, disabled, testId }: {
  on: boolean; onClick?: () => void; title: ReactNode; sub?: ReactNode; right?: ReactNode; disabled?: boolean; testId?: string;
}) {
  return (
    <button type="button" role="radio" aria-checked={on} onClick={onClick} disabled={disabled} data-testid={testId}
      className={cn("flex min-h-[52px] w-full items-center justify-between gap-2.5 rounded-xl border px-3 py-2 text-left text-[14.5px]",
        on ? "border-primary bg-[var(--haip-primary-tint)] shadow-[inset_0_0_0_1px_var(--primary)]" : "border-[var(--haip-border)] bg-[var(--haip-card)]",
        disabled && "opacity-60")}>
      <span aria-hidden className={cn("grid size-5 shrink-0 place-items-center rounded-full border-2", on ? "border-primary" : "border-[var(--haip-border-strong)]")}>
        {on && <span className="size-2.5 rounded-full bg-primary" />}
      </span>
      <span className="grid min-w-0 flex-1 gap-px">
        <b className="font-semibold">{title}</b>
        {sub && <span className="text-[12.5px] text-[var(--haip-fg-subtle)]">{sub}</span>}
      </span>
      {right}
    </button>
  );
}

export const HINT = "text-[13px] text-[var(--haip-fg-subtle)]";
