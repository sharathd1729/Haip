"use client";
// "Needs you now": the four live queues, each linking to the screen that
// clears it. Counts use the same definitions as those screens, so the
// number here matches what the agent sees after clicking through.
import Link from "next/link";
import { cn } from "@/lib/utils";
import { ago, type NeedsYouNow } from "./types";

interface Card {
  label: string; count: number; note: string; cta: string; href: string;
  bar: string; num: string; btn: string;
}

function cards(n: NeedsYouNow): Card[] {
  return [
    {
      label: "Guests waiting for a reply", count: n.waiting_reply,
      note: n.waiting_oldest_at ? `oldest ${ago(n.waiting_oldest_at)}` : "all answered",
      cta: "Reply now", href: "/dashboard/my-day?kind=reply",
      bar: "bg-orange-700", num: "text-orange-700", btn: "bg-amber-100 text-orange-800 hover:bg-amber-200",
    },
    {
      label: "Missed calls not called back", count: n.missed_not_called_back,
      note: n.missed_oldest_at ? `oldest ${ago(n.missed_oldest_at)}` : "all returned",
      cta: "Call back", href: "/dashboard/my-day?kind=callback",
      bar: "bg-red-700", num: "text-red-700", btn: "bg-red-100 text-red-800 hover:bg-red-200",
    },
    {
      label: "Shared a phone, not called", count: n.phone_not_called,
      note: "warm leads", cta: "Call them", href: "/dashboard/my-day?kind=call_new",
      bar: "bg-emerald-700", num: "text-emerald-700", btn: "bg-emerald-100 text-emerald-800 hover:bg-emerald-200",
    },
    {
      label: "Follow-ups overdue", count: n.followups_overdue,
      note: n.followups_oldest_due ? `due ${ago(n.followups_oldest_due)} ago` : "none overdue",
      cta: "See tasks", href: "/dashboard/my-day?kind=followup",
      bar: "bg-violet-700", num: "text-violet-700", btn: "bg-violet-100 text-violet-800 hover:bg-violet-200",
    },
  ];
}

export function NeedsYouNowCards({ data }: { data: NeedsYouNow }) {
  const list = cards(data);
  const total = list.reduce((s, c) => s + c.count, 0);
  return (
    <section>
      <h2 className="text-base font-bold mb-2.5" style={{ color: "var(--haip-fg)" }}>
        Needs you now{" "}
        <span className="text-xs font-normal" style={{ color: "var(--haip-fg-subtle)" }}>
          {total ? `${total} things across ${list.filter(c => c.count).length} queues` : "all clear"}
        </span>
      </h2>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {list.map(c => (
          <Link key={c.label} href={c.href}
            className="haip-card relative overflow-hidden pl-5 pr-4 py-3.5 flex flex-col gap-1 hover:shadow-md transition-shadow focus-visible:ring-2 focus-visible:ring-teal-600 outline-none">
            <span className={cn("absolute left-0 top-3 bottom-3 w-[3px] rounded-r", c.count ? c.bar : "bg-gray-300")} />
            <span className="text-[13px] font-semibold leading-snug" style={{ color: "var(--haip-fg)" }}>{c.label}</span>
            <span className="flex items-baseline gap-2">
              <span className={cn("text-3xl font-bold tabular-nums", c.count ? c.num : "text-gray-400")} style={{ fontFamily: "var(--font-display)" }}>
                {c.count}
              </span>
              <span className="text-xs" style={{ color: "var(--haip-fg-subtle)" }}>{c.note}</span>
            </span>
            <span className={cn("self-end text-xs font-bold px-3 py-1.5 rounded-lg mt-1", c.count ? c.btn : "bg-gray-100 text-gray-500 dark:bg-gray-800")}>
              {c.cta}
            </span>
          </Link>
        ))}
      </div>
    </section>
  );
}
