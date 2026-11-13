"use client";
// Yaad calls list: dated plans that came up on calls ("Upcoming"), then every call newest first, grouped by day.
// A row shows what the call was about once it is summarised, and plainly says why when it is not (yet).
import { Clock, Loader2, PhoneIncoming, PhoneOutgoing } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { STATUS_TEXT, dayLabel, durationLabel, groupByDay, timeLabel, type CallRow, type Upcoming } from "@/lib/personal";
import { useCallsPages } from "./hooks";

export function CallList({ selectedId, onSelect }: { selectedId?: string | null; onSelect: (id: string) => void }) {
  const q = useCallsPages();
  const calls = q.data?.pages.flatMap(p => p.calls) ?? [];
  const upcoming = q.data?.pages[0]?.upcoming ?? [];

  if (q.isPending) return <ListSkeleton />;
  if (q.isError) {
    return (
      <Notice title="Couldn't load your calls" body="Check your connection and try again.">
        <button type="button" onClick={() => q.refetch()} className="y-press mt-4 min-h-11 rounded-full bg-[var(--y-brand)] px-5 text-[15px] font-semibold text-[var(--y-on-brand)]">
          Try again
        </button>
      </Notice>
    );
  }
  if (calls.length === 0) {
    return (
      <Notice
        title="No calls yet"
        body="Open the Yaad app on your phone, sign in and allow call log access. Each call appears here a few minutes after it ends, with its summary and reminders."
      />
    );
  }

  return (
    <div className="grid gap-7">
      {upcoming.length > 0 && <UpcomingStrip items={upcoming} onSelect={onSelect} />}
      {groupByDay(calls).map(group => (
        <section key={group.day} aria-label={group.day ? dayLabel(group.day) : "Undated"} className="grid gap-2.5">
          <h2 className="px-1 text-[13px] font-semibold text-[var(--y-ink-2)]">{group.day ? dayLabel(group.day) : "Undated"}</h2>
          <ul className="grid gap-2.5">
            {group.rows.map(c => (
              <li key={c.id}><CallCard call={c} active={c.id === selectedId} onSelect={onSelect} /></li>
            ))}
          </ul>
        </section>
      ))}
      {q.hasNextPage && (
        <button
          type="button"
          onClick={() => q.fetchNextPage()}
          disabled={q.isFetchingNextPage}
          className="y-press min-h-11 justify-self-center rounded-full border border-[var(--y-line-strong)] bg-[var(--y-card)] px-5 text-[15px] font-medium text-[var(--y-ink)]"
        >
          {q.isFetchingNextPage ? "Loading…" : "Show older calls"}
        </button>
      )}
    </div>
  );
}

function CallCard({ call, active, onSelect }: { call: CallRow; active: boolean; onSelect: (id: string) => void }) {
  const Dir = call.direction === "in" ? PhoneIncoming : PhoneOutgoing;
  const working = call.status === "transcribing" || call.status === "analysing";
  return (
    <button
      type="button"
      onClick={() => onSelect(call.id)}
      aria-current={active ? "true" : undefined}
      className={cn(
        "y-press w-full rounded-[18px] border bg-[var(--y-card)] p-4 text-left shadow-[var(--y-shadow)] transition-colors duration-150",
        active ? "border-[var(--y-brand)]" : "border-[var(--y-line)] hover:border-[var(--y-line-strong)]",
      )}
    >
      <div className="flex items-center gap-1.5 text-[12.5px] text-[var(--y-ink-3)] [font-variant-numeric:tabular-nums]">
        <Dir size={13} aria-hidden />
        <span>{timeLabel(call.at)}</span>
        <span aria-hidden>·</span>
        <span>{durationLabel(call.duration_sec)}</span>
      </div>
      {call.title ? (
        <p className="mt-1.5 line-clamp-2 text-[16px] font-semibold leading-snug tracking-[-0.01em] text-[var(--y-ink)]">{call.title}</p>
      ) : (
        <p className="mt-1.5 flex items-center gap-1.5 text-[15px] text-[var(--y-ink-2)]">
          {working && <Loader2 size={14} className="animate-spin" aria-hidden />}
          {STATUS_TEXT[call.status] || "Call"}
        </p>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <span className="min-w-0 truncate text-[14px] text-[var(--y-ink-2)]">{call.contact}</span>
        {call.reminders_open > 0 && (
          <span className="rounded-full bg-[var(--y-soft)] px-2 py-0.5 text-[12px] font-semibold text-[var(--y-soft-ink)]">
            {call.reminders_open} {call.reminders_open === 1 ? "reminder" : "reminders"}
          </span>
        )}
      </div>
    </button>
  );
}

function UpcomingStrip({ items, onSelect }: { items: Upcoming[]; onSelect: (id: string) => void }) {
  return (
    <section aria-label="Upcoming" className="grid gap-2.5">
      <h2 className="px-1 text-[13px] font-semibold text-[var(--y-ink-2)]">Upcoming</h2>
      <ul className="-mx-4 flex snap-x snap-mandatory gap-2.5 overflow-x-auto px-4 pb-1 [scrollbar-width:none]">
        {items.map((u, i) => {
          const d = new Date(`${u.date}T00:00:00Z`);
          return (
            <li key={`${u.call_id}-${i}`} className="snap-start">
              <button
                type="button"
                onClick={() => onSelect(u.call_id)}
                className="y-press flex w-[250px] items-start gap-3 rounded-[18px] border border-[var(--y-line)] bg-[var(--y-card)] p-3.5 text-left shadow-[var(--y-shadow)]"
              >
                <span className="flex w-12 shrink-0 flex-col items-center rounded-xl bg-[var(--y-brand)] py-1.5 text-[var(--y-on-brand)]">
                  <span className="text-[11px] font-semibold uppercase tracking-wide">{d.toLocaleDateString("en-IN", { month: "short", timeZone: "UTC" })}</span>
                  <span className="text-[20px] font-bold leading-none [font-variant-numeric:tabular-nums]">{d.getUTCDate()}</span>
                </span>
                <span className="min-w-0">
                  <span className="line-clamp-2 text-[14.5px] font-semibold leading-snug text-[var(--y-ink)]">{u.what}</span>
                  <span className="mt-1 flex items-center gap-1 text-[12.5px] text-[var(--y-ink-2)]">
                    <Clock size={12} aria-hidden />
                    {[dayLabel(u.date), u.time, u.place].filter(Boolean).join(" · ")}
                  </span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function Notice({ title, body, children }: { title: string; body: string; children?: React.ReactNode }) {
  return (
    <div className="rounded-[22px] border border-dashed border-[var(--y-line-strong)] bg-[var(--y-card)] px-6 py-12 text-center">
      <p className="text-[17px] font-semibold text-[var(--y-ink)]">{title}</p>
      <p className="mx-auto mt-2 max-w-[42ch] text-[14.5px] leading-relaxed text-[var(--y-ink-2)]">{body}</p>
      {children}
    </div>
  );
}

function ListSkeleton() {
  return (
    <div className="grid gap-2.5" aria-busy="true" aria-label="Loading calls">
      {[0, 1, 2, 3].map(i => (
        <div key={i} className="h-[104px] animate-pulse rounded-[18px] border border-[var(--y-line)] bg-[var(--y-card)]" />
      ))}
    </div>
  );
}
