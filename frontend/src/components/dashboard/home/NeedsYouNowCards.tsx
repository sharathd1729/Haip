"use client";
// "Needs you now": the live queues, each linking to the My day list that clears it. The numbers are PEOPLE from the same work
// queue My day reads (a person is counted once), so what the card says is what the agent finds after clicking through.
import Link from "next/link";
import { cn } from "@/lib/utils";
import { ago, type NeedsYouNow } from "./types";

interface Card {
  label: string; count: number; note: string; cta: string; href: string; tone: "danger" | "warning" | "info";
}

const TONE = {
  danger: { bar: "bg-[var(--haip-status-danger-fg)]", num: "text-[var(--haip-status-danger-fg)]", btn: "bg-[var(--haip-status-danger-bg)] text-[var(--haip-status-danger-fg)]" },
  warning: { bar: "bg-[var(--haip-status-warning-fg)]", num: "text-[var(--haip-status-warning-fg)]", btn: "bg-[var(--haip-status-warning-bg)] text-[var(--haip-status-warning-fg)]" },
  info: { bar: "bg-[var(--haip-status-info-fg)]", num: "text-[var(--haip-status-info-fg)]", btn: "bg-[var(--haip-status-info-bg)] text-[var(--haip-status-info-fg)]" },
};

function cards(n: NeedsYouNow): Card[] {
  return [
    {
      label: "New leads to contact", count: n.new_leads,
      note: n.new_leads_oldest_at ? `oldest ${ago(n.new_leads_oldest_at)}` : "all contacted",
      cta: "Call them", href: "/dashboard/my-day?kind=new_lead", tone: "danger",
    },
    {
      label: "Missed calls to return", count: n.missed_not_called_back,
      note: n.missed_oldest_at ? `oldest ${ago(n.missed_oldest_at)}` : "all returned",
      cta: "Call back", href: "/dashboard/my-day?kind=callback", tone: "danger",
    },
    {
      label: "Leads waiting for a reply", count: n.waiting_reply,
      note: n.waiting_oldest_at ? `oldest ${ago(n.waiting_oldest_at)}` : "all answered",
      cta: "Reply now", href: "/dashboard/my-day?kind=reply", tone: "warning",
    },
    {
      label: "Follow-ups overdue", count: n.followups_overdue,
      note: n.followups_oldest_due ? `due ${ago(n.followups_oldest_due)} ago` : "none overdue",
      cta: "See tasks", href: "/dashboard/my-day?kind=followup", tone: "info",
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
          {total ? `${data.people} ${data.people === 1 ? "person" : "people"} waiting${data.breached ? `, ${data.breached} past their target time` : ""}` : "all clear"}
        </span>
      </h2>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {list.map(c => {
          const t = TONE[c.tone];
          return (
            <Link key={c.label} href={c.href}
              className="haip-card relative overflow-hidden pl-5 pr-4 py-3.5 flex flex-col gap-1 hover:shadow-md transition-shadow focus-visible:ring-2 focus-visible:ring-primary outline-none">
              <span className={cn("absolute left-0 top-3 bottom-3 w-[3px] rounded-r", c.count ? t.bar : "bg-[var(--haip-border)]")} />
              <span className="text-[13px] font-semibold leading-snug" style={{ color: "var(--haip-fg)" }}>{c.label}</span>
              <span className="flex items-baseline gap-2">
                <span className={cn("text-3xl font-bold tabular-nums", c.count ? t.num : "text-[var(--haip-fg-subtle)]")} style={{ fontFamily: "var(--font-display)" }}>
                  {c.count}
                </span>
                <span className="text-xs" style={{ color: "var(--haip-fg-subtle)" }}>{c.note}</span>
              </span>
              <span className={cn("self-end text-xs font-bold px-3 py-1.5 rounded-lg mt-1", c.count ? t.btn : "bg-[var(--haip-surface)] text-[var(--haip-fg-subtle)]")}>
                {c.cta}
              </span>
            </Link>
          );
        })}
      </div>
    </section>
  );
}
