"use client";
// Yaad reminders: every action item from your calls, open first by when it is due, or the ones already done.
import { useState } from "react";
import { cn } from "@/lib/utils";
import { istDay, isMine, type Reminder } from "@/lib/personal";
import { useReminders } from "@/components/personal/hooks";
import { ReminderRow } from "@/components/personal/ReminderRow";
import { YaadWordmark } from "@/components/personal/YaadMark";

type Who = "all" | "mine" | "others";

function groups(items: Reminder[]): { title: string; items: Reminder[] }[] {
  const today = istDay(new Date());
  const pick = (f: (r: Reminder) => boolean) => items.filter(f);
  return [
    { title: "Overdue", items: pick(r => !!r.due && r.due < today) },
    { title: "Today", items: pick(r => r.due === today) },
    { title: "Coming up", items: pick(r => !!r.due && r.due > today) },
    { title: "No date", items: pick(r => !r.due) },
  ].filter(g => g.items.length > 0);
}

export default function YaadRemindersPage() {
  const [tab, setTab] = useState<"open" | "done">("open");
  const [who, setWho] = useState<Who>("all");
  const q = useReminders(tab);
  const all = q.data?.reminders ?? [];
  const items = all.filter(r => who === "all" || (who === "mine") === isMine(r.owner));

  return (
    <div className="yaad min-h-full px-4 py-5 sm:px-6">
      <div className="mx-auto max-w-[680px]">
        <div className="mb-5 hidden min-[600px]:block"><YaadWordmark /></div>
        <h1 className="text-[26px] font-semibold tracking-[-0.02em]">Reminders</h1>
        <p className="mt-1 text-[14.5px] text-[var(--y-ink-2)]">What you and others said you would do, from your calls.</p>

        <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
          <Segmented value={tab} onChange={v => setTab(v as "open" | "done")} label="Show" options={[["open", "To do"], ["done", "Done"]]} />
          <Segmented value={who} onChange={v => setWho(v as Who)} label="Whose" options={[["all", "All"], ["mine", "Mine"], ["others", "Others'"]]} />
        </div>

        <div className="mt-6">
          {q.isPending ? (
            <div className="grid gap-3" aria-busy="true" aria-label="Loading reminders">
              {[0, 1, 2].map(i => <div key={i} className="h-20 animate-pulse rounded-[18px] bg-[var(--y-line)]" />)}
            </div>
          ) : q.isError ? (
            <div className="rounded-[18px] border border-[var(--y-line)] bg-[var(--y-card)] p-6 text-center">
              <p className="font-semibold">Couldn't load your reminders</p>
              <button type="button" onClick={() => q.refetch()} className="y-press mt-3 min-h-11 rounded-full bg-[var(--y-brand)] px-5 text-[15px] font-semibold text-[var(--y-on-brand)]">Try again</button>
            </div>
          ) : items.length === 0 ? (
            <div className="rounded-[22px] border border-dashed border-[var(--y-line-strong)] bg-[var(--y-card)] px-6 py-12 text-center">
              <p className="text-[17px] font-semibold">{tab === "open" ? "Nothing to do" : "Nothing done yet"}</p>
              <p className="mx-auto mt-2 max-w-[40ch] text-[14.5px] text-[var(--y-ink-2)]">
                {tab === "open" ? "When a call has something to follow up, it appears here with who owns it and when it is due." : "Reminders you tick off appear here."}
              </p>
            </div>
          ) : tab === "done" ? (
            <ul className="rounded-[20px] border border-[var(--y-line)] bg-[var(--y-card)] px-4 py-1">
              {items.map(r => <ReminderRow key={`${r.call_id}-${r.id}`} item={r} callId={r.call_id} source={{ title: r.call_title, contact: r.contact }} />)}
            </ul>
          ) : (
            <div className="grid gap-6">
              {groups(items).map(g => (
                <section key={g.title} aria-label={g.title}>
                  <h2 className={cn("mb-2 px-1 text-[13px] font-semibold", g.title === "Overdue" ? "text-[var(--y-late)]" : "text-[var(--y-ink-2)]")}>
                    {g.title} · {g.items.length}
                  </h2>
                  <ul className="rounded-[20px] border border-[var(--y-line)] bg-[var(--y-card)] px-4 py-1 shadow-[var(--y-shadow)]">
                    {g.items.map(r => <ReminderRow key={`${r.call_id}-${r.id}`} item={r} callId={r.call_id} source={{ title: r.call_title, contact: r.contact }} />)}
                  </ul>
                </section>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Segmented({ value, onChange, options, label }: {
  value: string; onChange: (v: string) => void; options: [string, string][]; label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-full border border-[var(--y-line)] bg-[var(--y-card)] p-1">
      {options.map(([v, text]) => (
        <button
          key={v}
          type="button"
          role="radio"
          aria-checked={value === v}
          onClick={() => onChange(v)}
          className={cn(
            "y-press min-h-9 rounded-full px-4 text-[14px] font-medium transition-colors duration-150",
            value === v ? "bg-[var(--y-brand)] text-[var(--y-on-brand)]" : "text-[var(--y-ink-2)] hover:text-[var(--y-ink)]",
          )}
        >
          {text}
        </button>
      ))}
    </div>
  );
}
