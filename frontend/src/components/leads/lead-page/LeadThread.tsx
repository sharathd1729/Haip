"use client";
// The conversation, WhatsApp style: oldest at the top, newest just above the composer, a day separator between
// days. Calls, quotes, bookings, stage changes, tasks and merges sit inline at the moment they happened.
import { Fragment, useState } from "react";
import { cn } from "@/lib/utils";
import { EmptyState } from "@/components/ui/page";
import { BookingCard, CallCard, MessageBubble, QuoteCard, SysLine } from "./ThreadItems";
import { dayLabel, sameDay } from "./format";
import type { FeedItem, FeedKind } from "./types";

type Filter = "all" | "message" | "call" | "deal" | "update";
const FILTERS: { key: Filter; label: string; kinds: FeedKind[] | null }[] = [
  { key: "all", label: "All", kinds: null },
  { key: "message", label: "Messages", kinds: ["message"] },
  { key: "call", label: "Calls", kinds: ["call"] },
  { key: "deal", label: "Quotes & bookings", kinds: ["quote", "booking"] },
  { key: "update", label: "Stage & tasks", kinds: ["stage", "task", "merge"] },
];

export function LeadThread({ items, inquiryId, canSend, canOpenBookings, capped, messagesRestricted, now }: {
  items: FeedItem[]; inquiryId: string; canSend: boolean; canOpenBookings: boolean; capped: boolean; messagesRestricted: boolean; now?: Date;
}) {
  const [filter, setFilter] = useState<Filter>("all");
  const kinds = FILTERS.find(f => f.key === filter)?.kinds;
  const shown = kinds ? items.filter(i => kinds.includes(i.kind)) : items;

  return (
    <div className="grid gap-2">
      <div role="group" aria-label="Show in the conversation" className="-mx-1 flex gap-1.5 overflow-x-auto px-1 pb-0.5 [scrollbar-width:none]">
        {FILTERS.map(f => {
          const n = f.kinds ? items.filter(i => f.kinds!.includes(i.kind)).length : items.length;
          return (
            <button key={f.key} type="button" aria-pressed={filter === f.key} onClick={() => setFilter(f.key)}
              className={cn("inline-flex min-h-11 shrink-0 items-center gap-1 rounded-full border px-3 text-[13px] font-semibold sm:min-h-9",
                filter === f.key ? "border-primary bg-primary text-primary-foreground" : "border-[var(--haip-border-strong)] bg-[var(--haip-card)] text-[var(--haip-fg-2)]")}>
              {f.label}<span className="opacity-70 tabular-nums">{n}</span>
            </button>
          );
        })}
      </div>

      {capped && <p className="text-center text-[12.5px] text-[var(--haip-fg-subtle)]">Showing the latest 50. Older activity is on the Calls page and in the Inbox.</p>}
      {messagesRestricted && <p className="text-center text-[12.5px] text-[var(--haip-fg-subtle)]">Messages are hidden for your role. Calls, quotes and updates still show.</p>}

      {shown.length === 0 ? (
        <EmptyState className="py-10" title={filter === "all" ? "Nothing here yet" : "Nothing of this kind yet"}
          hint={filter === "all" ? "Calls, messages, quotes and stage changes with this person will appear here as they happen." : undefined} />
      ) : (
        <ol className="grid gap-2 pb-2" aria-label="Conversation">
          {shown.map((item, i) => (
            <Fragment key={item.id}>
              {(i === 0 || !sameDay(shown[i - 1].at, item.at)) && (
                <li className="my-1.5 justify-self-center rounded-full border border-[var(--haip-border)] bg-[var(--haip-surface)] px-3 py-0.5 text-[12px] font-bold text-[var(--haip-fg-subtle)]">
                  {dayLabel(item.at, now)}
                </li>
              )}
              <li className="grid">
                {item.kind === "message" ? <MessageBubble item={item} canSend={canSend} inquiryId={inquiryId} />
                  : item.kind === "call" ? <CallCard item={item} />
                  : item.kind === "quote" ? <QuoteCard item={item} />
                  : item.kind === "booking" ? <BookingCard item={item} canOpen={canOpenBookings} />
                  : <SysLine item={item} />}
              </li>
            </Fragment>
          ))}
        </ol>
      )}
    </div>
  );
}
