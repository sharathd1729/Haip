"use client";
// One reminder (an action item from a call): a large check target, the task, who owns it, and when it is due.
import Link from "next/link";
import { Check } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { dueLabel, isMine, ownerLabel, type ActionItem } from "@/lib/personal";
import { useToggleReminder } from "./hooks";

export function ReminderRow({ item, callId, source }: {
  item: ActionItem;
  callId: string;
  /** Where it came from, shown on the Reminders page (call title and person). */
  source?: { title: string | null; contact: string };
}) {
  const toggle = useToggleReminder();
  const done = item.done;
  const due = dueLabel(item.due);
  return (
    <li className="flex items-start gap-1">
      <button
        type="button"
        role="checkbox"
        aria-checked={done}
        aria-label={done ? `Mark "${item.text}" as not done` : `Mark "${item.text}" as done`}
        onClick={() => toggle.mutate({ callId, id: item.id, done: !done })}
        className="y-press -ml-2 flex size-11 shrink-0 items-center justify-center rounded-full"
      >
        <span className={cn(
          "flex size-[22px] items-center justify-center rounded-[7px] border-2 transition-colors duration-150",
          done ? "border-[var(--y-brand)] bg-[var(--y-brand)] text-[var(--y-on-brand)]" : "border-[var(--y-line-strong)] bg-[var(--y-card)]",
        )}>
          {done && <Check size={14} strokeWidth={3} />}
        </span>
      </button>
      <div className="min-w-0 flex-1 py-2.5">
        <p className={cn("text-[15px] leading-snug transition-colors duration-150", done ? "text-[var(--y-ink-3)] line-through" : "text-[var(--y-ink)]")}>
          {item.text}
        </p>
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[12.5px]">
          <span className={cn(
            "rounded-full px-2 py-0.5 font-semibold",
            isMine(item.owner) ? "bg-[var(--y-soft)] text-[var(--y-soft-ink)]" : "border border-[var(--y-line)] text-[var(--y-ink-2)]",
          )}>
            {ownerLabel(item.owner)}
          </span>
          {due.text && !done && (
            <span className={cn(
              "rounded-full px-2 py-0.5 font-semibold",
              due.overdue ? "bg-[var(--y-late-soft)] text-[var(--y-late)]" : "bg-[var(--y-due)] text-[var(--y-on-due)]",
            )}>
              {due.text}
            </span>
          )}
        </div>
        {item.context && <p className="mt-1.5 text-[13px] leading-snug text-[var(--y-ink-2)]">{item.context}</p>}
        {source && (
          <Link href={`/dashboard/me/calls/${callId}`} className="mt-1.5 inline-block text-[13px] font-medium text-[var(--y-brand)] underline-offset-2 hover:underline">
            From {source.title ? `"${source.title}"` : "a call"} with {source.contact}
          </Link>
        )}
      </div>
    </li>
  );
}
