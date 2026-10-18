"use client";
// After "Send quote + payment link": link created -> sent on WhatsApp -> paid -> booking -> invoice -> confirmation
// (docs/design/bookings-mockup/quotes.html, journeyCard). Live: GET /quotes/{id} every 20 s, only while a link is unpaid.
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Check, Copy, Loader2 } from "@/lib/icons";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";
import { StatusPill } from "@/components/ui/kit";
import { money } from "@/app/dashboard/quotes/quoteHelpers";
import { journeySteps, type StepState } from "@/app/dashboard/quotes/sendHelpers";
import type { Journey, QuoteDetail } from "@/app/dashboard/quotes/types";
import { BTN, Callout } from "./ui";

const DOT: Record<StepState, string> = {
  done: "bg-primary text-primary-foreground",
  waiting: "border border-[var(--haip-border-strong)] bg-[var(--haip-card)]",
  problem: "bg-[var(--haip-status-danger-bg)] text-[var(--haip-status-danger-fg)] border border-[var(--haip-status-danger-border)]",
};
const LINK_PILL = { created: ["Unpaid", "info"], paid: ["Paid", "success"], expired: ["Expired", "neutral"], cancelled: ["Cancelled", "neutral"] } as const;

export function QuoteJourney({ quoteId, initial, notice, onNewQuote }: {
  quoteId: string; initial: Journey; notice: string | null; onNewQuote: () => void;
}) {
  const { toast } = useToast();
  const live = useQuery<QuoteDetail>({
    queryKey: ["quote", quoteId],
    queryFn: () => api.get(`/quotes/${quoteId}`).then(r => r.data),
    refetchInterval: q => ((q.state.data?.send ?? initial).polling ? 20_000 : false),
    refetchIntervalInBackground: false,
    retry: 1,
  });
  const j = live.data?.send ?? initial;
  const steps = journeySteps(j);
  const many = j.options.length > 1;

  const copy = (url: string) => navigator.clipboard?.writeText(url).then(
    () => toast({ variant: "success", title: "Link copied" }),
    () => toast({ variant: "error", title: "Could not copy", description: url }),
  );

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <p className="min-w-0 flex-1 text-[13.5px] font-semibold">Quote {j.quote_number}</p>
        {j.polling && <span className="inline-flex items-center gap-1 text-xs text-[var(--haip-fg-subtle)]"><Loader2 size={12} className="animate-spin" /> Checking every 20 s</span>}
      </div>
      {notice && <Callout tone="warning">{notice}</Callout>}
      {live.isError && <Callout tone="danger">Couldn&apos;t refresh the status. It will try again; the links below still work.</Callout>}

      <ol className="space-y-3" aria-label="What happens after sending">
        {steps.map(s => (
          <li key={s.key} className="flex gap-3">
            <span aria-hidden className={cn("mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full text-[11px] font-bold", DOT[s.state])}>
              {s.state === "done" ? <Check size={12} /> : s.state === "problem" ? "!" : ""}
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-[13.5px] font-semibold">{s.title}
                <span className="sr-only">{s.state === "done" ? " (done)" : s.state === "problem" ? " (needs you)" : " (waiting)"}</span>
              </p>
              <p className="text-[12.5px] leading-snug text-[var(--haip-fg-subtle)] [overflow-wrap:anywhere]">{s.detail}</p>
              {s.key === "booking" && j.booking_id && (
                <Link href={`/dashboard/bookings/${j.booking_id}`} className="mt-1 inline-flex min-h-11 items-center text-[13px] font-semibold text-primary hover:underline sm:min-h-8">
                  Open the booking
                </Link>
              )}
            </div>
          </li>
        ))}
      </ol>

      <div className="space-y-2">
        {j.options.map(o => o.link && (
          <div key={o.quote_id} className="flex flex-wrap items-center gap-2 rounded-xl border border-[var(--haip-border)] px-3 py-2">
            <div className="min-w-0 flex-1">
              <p className="text-[13px] font-semibold">{many ? (o.option_rank === 2 ? "Option 2" : "Option 1") : "Payment link"} · {money(o.link.amount)}</p>
              <p className="truncate text-[12px] text-[var(--haip-fg-subtle)]">{o.link.short_url}</p>
            </div>
            <StatusPill tone={LINK_PILL[o.link.status][1]}>{LINK_PILL[o.link.status][0]}</StatusPill>
            <button type="button" className={BTN} onClick={() => copy(o.link!.short_url)} aria-label={`Copy the ${many ? `option ${o.option_rank} ` : ""}payment link`}>
              <Copy size={13} /> Copy link
            </button>
          </div>
        ))}
      </div>
      {many && !j.paid && (
        <p className="text-xs text-[var(--haip-fg-subtle)]">
          The WhatsApp button opens option 1. Option 2&apos;s link goes as a separate message only if the guest wrote in the last 24 hours; otherwise copy it.
        </p>
      )}
      <button type="button" className={BTN} onClick={onNewQuote}>Start a new quote</button>
    </div>
  );
}
