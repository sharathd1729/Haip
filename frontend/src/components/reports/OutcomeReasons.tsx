"use client";
// Reports > Why we win / lose (lead_outcome). GET /reports/outcome-reasons (owner/manager + analytics.read): won and lost
// guest leads by reason, by the date they closed (or their check-in). Confirmed reasons (a person, a person confirming the
// AI, a rule) are shown apart from the AI's unconfirmed proposals; never added into one bar. Phone first: one list per side.
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Card, CardBody, CardHeader, EmptyState, Tabs } from "@/components/ui/kit";

interface Reason { reason: string; label: string; confirmed: number; proposed: number }
interface Side { total: number; confirmed: number; proposed: number; not_recorded: number; reasons: Reason[] }
interface Report { from: string; to: string; basis: "closed" | "checkin"; skipped: number; won: Side; lost: Side; definitions: Record<string, string> }

const day = (iso: string) => new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-GB", { timeZone: "UTC", day: "numeric", month: "short", year: "numeric" });

function Bars({ side, tone }: { side: Side; tone: "success" | "danger" }) {
  const rows = side.reasons.filter(r => r.confirmed + r.proposed > 0);
  const max = Math.max(1, ...rows.map(r => r.confirmed + r.proposed));
  if (!rows.length) return <p className="text-[13.5px] text-[var(--haip-fg-muted)]">No reasons recorded yet.</p>;
  return (
    <ul className="grid gap-2">
      {rows.map(r => (
        <li key={r.reason} className="grid gap-1">
          <span className="flex items-baseline justify-between gap-2 text-[13.5px]">
            <span className="text-[var(--haip-fg)]">{r.label}</span>
            <span className="tabular-nums text-[var(--haip-fg-2)]">{r.confirmed}{r.proposed ? <span className="text-[var(--haip-fg-subtle)]"> + {r.proposed} proposed</span> : null}</span>
          </span>
          <svg viewBox="0 0 100 10" preserveAspectRatio="none" className="h-2.5 w-full overflow-hidden rounded-full bg-[var(--haip-surface)]" aria-hidden>
            <rect x={0} y={0} height={10} width={(r.confirmed / max) * 100}
              className={tone === "success" ? "fill-[var(--haip-status-success-fg)]" : "fill-[var(--haip-status-danger-fg)]"} />
            <rect x={(r.confirmed / max) * 100} y={0} height={10} width={(r.proposed / max) * 100}
              className={cn("opacity-35", tone === "success" ? "fill-[var(--haip-status-success-fg)]" : "fill-[var(--haip-status-danger-fg)]")} />
          </svg>
        </li>
      ))}
    </ul>
  );
}

export function OutcomeReasons() {
  const [basis, setBasis] = useState<"closed" | "checkin">("closed");
  const q = useQuery<Report>({
    queryKey: ["report-outcome-reasons", basis],
    queryFn: () => api.get("/reports/outcome-reasons", { params: { basis } }).then(r => r.data),
    staleTime: 5 * 60_000,
  });
  const r = q.data;
  return (
    <Card>
      <CardHeader title="Why we win / lose" description={r ? `Guest leads ${basis === "closed" ? "closed" : "checking in"} ${day(r.from)} – ${day(r.to)}. Read from the calls and chats, confirmed by the team.` : "Won and lost leads by reason."} />
      <CardBody className="grid gap-4">
        <Tabs label="Count by" value={basis} onChange={v => setBasis(v as typeof basis)} className="w-full sm:w-fit"
          items={[{ value: "closed", label: "Date closed" }, { value: "checkin", label: "Check-in date" }]} />
        {q.isPending ? (
          <p className="text-sm text-[var(--haip-fg-muted)]">Loading…</p>
        ) : q.isError || !r ? (
          <EmptyState title="Couldn't load the report" hint="Check your connection and try again."
            action={<button type="button" onClick={() => q.refetch()} className="min-h-11 rounded-xl bg-primary px-4 text-[14px] font-semibold text-primary-foreground">Try again</button>} />
        ) : r.won.total + r.lost.total === 0 ? (
          <EmptyState title="No won or lost leads in this period" />
        ) : (
          <div className="grid gap-5 md:grid-cols-2">
            {(["lost", "won"] as const).map(k => (
              <section key={k} className="grid content-start gap-2">
                <h3 className="text-[15px] font-semibold text-[var(--haip-fg)]">{k === "won" ? "Why we won" : "Why we lost"} · {r[k].total}</h3>
                <p className="text-[12.5px] text-[var(--haip-fg-subtle)]">{r[k].confirmed} confirmed · {r[k].proposed} proposed by AI · {r[k].not_recorded} not recorded yet</p>
                <Bars side={r[k]} tone={k === "won" ? "success" : "danger"} />
              </section>
            ))}
          </div>
        )}
        {r && <p className="text-[12.5px] text-[var(--haip-fg-subtle)]">{r.definitions.confirmed} Proposed: {r.definitions.proposed}{r.skipped ? ` ${r.skipped} with an unreadable check-in are not counted.` : ""}</p>}
      </CardBody>
    </Card>
  );
}
