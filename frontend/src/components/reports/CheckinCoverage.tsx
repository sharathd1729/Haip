"use client";
// Reports > Check-in coverage (CRM reporting, 22 Oct 2026). GET /reports/checkin-coverage (owner/manager): valid guest
// enquiries per upcoming weekend (Fri-Sun) and per check-in date against a target, with the vehicles already booked.
// "Reviewed" = a person marked it Valid; "by stage" = not reviewed, in a valid stage. Phone first: cards, no wide table.
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Card, CardBody, CardHeader, EmptyState, StatusPill } from "@/components/ui/kit";

interface Cover { valid: number; reviewed_valid: number; stage_valid: number; below_target: boolean; booked_vehicles: string[] }
interface Day extends Cover { date: string; weekday: string; is_weekend: boolean }
interface Weekend extends Cover { friday: string; sunday: string; partial: boolean }
interface Coverage { from: string; to: string; target: number; vehicles: string[]; days: Day[]; weekends: Weekend[]; unparsed: number; basis: string;
  no_date_valid?: number; basis_kind?: "rule" | "stage" }

const day = (iso: string, opts: Intl.DateTimeFormatOptions = { day: "numeric", month: "short" }) =>
  new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-GB", { timeZone: "UTC", ...opts });

function Count({ c, target, by }: { c: Cover; target: number; by: string }) {
  return (
    <span className="flex items-baseline gap-1.5">
      <span className={cn("font-[family-name:var(--font-display)] text-[22px] font-semibold tabular-nums",
        c.below_target ? "text-[var(--haip-status-danger-fg)]" : "text-[var(--haip-fg)]")}>{c.valid}</span>
      <span className="text-[12.5px] text-[var(--haip-fg-subtle)]">of {target} · {c.reviewed_valid} reviewed, {c.stage_valid} {by}</span>
    </span>
  );
}

function Booked({ names, total }: { names: string[]; total: number }) {
  return (
    <span className="text-[12.5px] text-[var(--haip-fg-muted)]">
      {names.length ? `Booked: ${names.join(", ")}` : "No vehicle booked"}{total ? ` (${names.length} of ${total})` : ""}
    </span>
  );
}

export function CheckinCoverage() {
  const [showDays, setShowDays] = useState(false);
  const q = useQuery<Coverage>({
    queryKey: ["report-checkin-coverage"],
    queryFn: () => api.get("/reports/checkin-coverage").then(r => r.data),
    staleTime: 5 * 60_000,
  });
  const c = q.data;
  const by = c?.basis_kind === "rule" ? "by rule" : "by stage";
  return (
    <Card>
      <CardHeader title="Check-in coverage" description={c ? `Valid guest enquiries by check-in, ${day(c.from)} – ${day(c.to)}. Target ${c.target} per date and per weekend.` : "Valid guest enquiries by check-in date."} />
      <CardBody className="grid gap-4">
        {q.isPending ? (
          <p className="text-sm text-[var(--haip-fg-muted)]">Loading…</p>
        ) : q.isError || !c ? (
          <EmptyState title="Couldn't load coverage" hint="Check your connection and try again."
            action={<button type="button" onClick={() => q.refetch()} className="min-h-11 rounded-xl bg-primary px-4 text-[14px] font-semibold text-primary-foreground">Try again</button>} />
        ) : c.weekends.length === 0 && c.days.length === 0 ? (
          <EmptyState title="No dates in range" />
        ) : (
          <>
            <ul className="grid gap-2 sm:grid-cols-2">
              {c.weekends.map(w => (
                <li key={w.friday} className="grid gap-1 rounded-xl border border-[var(--haip-border)] px-3 py-2.5">
                  <span className="flex flex-wrap items-center justify-between gap-2">
                    <strong className="text-[14px] text-[var(--haip-fg)]">Weekend {day(w.friday)} – {day(w.sunday)}{w.partial ? " (part)" : ""}</strong>
                    {w.below_target ? <StatusPill tone="danger">Below target</StatusPill> : <StatusPill tone="success">On target</StatusPill>}
                  </span>
                  <Count c={w} target={c.target} by={by} />
                  <Booked names={w.booked_vehicles} total={c.vehicles.length} />
                </li>
              ))}
            </ul>
            <button type="button" onClick={() => setShowDays(v => !v)} aria-expanded={showDays}
              className="inline-flex min-h-11 items-center justify-self-start text-[13.5px] font-semibold text-primary">
              {showDays ? "Hide each date" : "Show each date"}
            </button>
            {showDays && (
              <ul className="grid gap-1.5">
                {c.days.map(d => (
                  <li key={d.date} className={cn("flex flex-wrap items-center justify-between gap-x-3 gap-y-1 rounded-lg px-3 py-2",
                    d.is_weekend ? "bg-[var(--haip-surface)]" : "border border-[var(--haip-border)]")}>
                    <span className="min-w-[96px] text-[13.5px] font-semibold text-[var(--haip-fg)]">{d.weekday} {day(d.date)}</span>
                    <Count c={d} target={c.target} by={by} />
                    <Booked names={d.booked_vehicles} total={c.vehicles.length} />
                  </li>
                ))}
              </ul>
            )}
            {!!c.no_date_valid && (
              <p className="rounded-xl border border-[var(--haip-border)] px-3 py-2 text-[13.5px] text-[var(--haip-fg-2)]">
                <strong className="text-[var(--haip-fg)]">{c.no_date_valid}</strong> valid open enquir{c.no_date_valid === 1 ? "y has" : "ies have"} no check-in date yet (not in any date above). Ask them for dates.
              </p>
            )}
            <p className="text-[12.5px] text-[var(--haip-fg-subtle)]">
              {c.basis}{c.unparsed ? ` ${c.unparsed} enquir${c.unparsed === 1 ? "y has" : "ies have"} a check-in we could not read and ${c.unparsed === 1 ? "is" : "are"} not counted.` : ""}
            </p>
          </>
        )}
      </CardBody>
    </Card>
  );
}
