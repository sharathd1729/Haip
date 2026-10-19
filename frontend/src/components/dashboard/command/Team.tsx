"use client";
// Agent performance for the period: what each person was given, what they did, and what became of it. On a phone each
// agent is a card with a two-column grid of figures; from the laptop width the same markup lines up as a table row.
// "—" means unknown (no data), never zero. Bookings and value are credited to whoever owns the lead now.
import type { ReactNode } from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { Empty, SectionTitle } from "./parts";
import { duration, inr, num, type AgentRow } from "./types";

const COLS = "lg:grid-cols-[minmax(0,1.5fr)_repeat(8,minmax(0,1fr))]";
const HEAD = ["New leads (qualified)", "Bookings", "Calls answered / missed", "Callbacks waiting", "First reply", "Messages sent", "Follow-ups done / overdue", "Call quality"];

function Stat({ label, children, tone }: { label: string; children: ReactNode; tone?: "danger" }) {
  return (
    <span className={cn("min-w-0 text-[13px] tabular-nums lg:text-right", tone === "danger" ? "font-semibold text-[var(--haip-status-danger-fg)]" : "text-[var(--haip-fg)]")}>
      <span className="block text-[11px] font-normal text-[var(--haip-fg-subtle)] lg:hidden">{label}</span>{children}
    </span>
  );
}

const SOURCE_SHORT = { personal_whatsapp: "Personal WA", whatsapp_cloud: "Business WA", instagram: "Instagram" } as const;

/** The first reply split by where the guest wrote, only for the sources the agent answered on. */
function BySource({ row }: { row: AgentRow }) {
  const parts = (Object.keys(SOURCE_SHORT) as (keyof typeof SOURCE_SHORT)[])
    .map(k => [k, row.response_by_source?.[k]] as const)
    .filter(([, v]) => v && v.response_count > 0);
  if (parts.length === 0) return null;
  return (
    <span className="block text-[11px] leading-snug text-[var(--haip-fg-subtle)]">
      {parts.map(([k, v]) => `${SOURCE_SHORT[k]} ${duration(v!.avg_seconds)}`).join(" · ")}
    </span>
  );
}

export function Team({ rows }: { rows: AgentRow[] }) {
  return (
    <section aria-labelledby="team-title" className="haip-card px-4 py-4 sm:px-6 sm:py-5">
      <SectionTitle sub="Leads are people with a phone number, credited to whoever owns them now; bookings are those made by those people"
        actions={<Link href="/dashboard/operations" className="inline-flex min-h-11 items-center text-[12.5px] font-semibold text-primary hover:underline lg:min-h-0">Full response-time view</Link>}>
        <span id="team-title">Agent performance</span>
      </SectionTitle>
      {rows.length === 0 ? <Empty>No agent activity in this period.</Empty> : (
        <>
          <div className={cn("hidden gap-x-3 border-b border-[var(--haip-border)] pb-1.5 text-[11.5px] font-semibold leading-tight text-[var(--haip-fg-subtle)] lg:grid", COLS)}>
            <span>Agent</span>{HEAD.map(h => <span key={h} className="text-right">{h}</span>)}
          </div>
          <ul className="divide-y divide-[var(--haip-border)]">
            {rows.map(a => (
              <li key={a.agent_id ?? "none"} className={cn("grid grid-cols-2 gap-x-3 gap-y-2.5 py-3.5 sm:grid-cols-3 lg:items-center lg:py-2.5", COLS)}>
                <span className={cn("col-span-2 min-w-0 truncate text-[14px] font-semibold sm:col-span-3 lg:col-span-1 lg:text-[13px]", a.agent_id ? "text-[var(--haip-fg)]" : "font-medium text-[var(--haip-fg-subtle)]")}>{a.name}</span>
                <Stat label="New leads (qualified)">{num(a.leads)} <span className="text-[var(--haip-fg-subtle)]">({num(a.qualified)})</span></Stat>
                <Stat label="Bookings">{a.bookings == null ? "—" : num(a.bookings)}{a.booking_value != null && <span className="block text-[11.5px] text-[var(--haip-fg-subtle)]">{inr(a.booking_value)}</span>}</Stat>
                <Stat label="Calls answered / missed">{a.agent_id ? `${num(a.calls_answered)} / ${num(a.calls_missed)}` : "—"}</Stat>
                <Stat label="Callbacks waiting" tone={a.callbacks_waiting > 0 ? "danger" : undefined}>{a.agent_id ? num(a.callbacks_waiting) : "—"}</Stat>
                <Stat label="First reply">{duration(a.avg_response_seconds)}<BySource row={a} /></Stat>
                <Stat label="Messages sent">{a.agent_id ? num(a.messages_sent) : "—"}</Stat>
                <Stat label="Follow-ups done / overdue" tone={a.followups_overdue > 0 ? "danger" : undefined}>{a.agent_id ? `${num(a.followups_completed)} / ${num(a.followups_overdue)}` : "—"}</Stat>
                <Stat label="Call quality">{a.avg_call_score == null ? "—" : `${a.avg_call_score}%`}</Stat>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-[11.5px] text-[var(--haip-fg-subtle)]">
            First reply is the average time to a human reply on WhatsApp and Instagram; the line under it splits it by where the guest wrote (personal WhatsApp leaves out group chats and mirrored phone history). Call quality is the average AI score of the agent’s analysed calls.
          </p>
        </>
      )}
    </section>
  );
}
