"use client";
// Reports > Daily lead report (CRM reporting, 22 Oct 2026). GET /reports/daily-validation?date= (owner/manager): per agent
// and in total, what the records say (received, handled, in a valid stage, conversions) kept apart from what a PERSON said
// on the lead page's "Valid enquiry?" card (reviewed, valid, not valid, not yet reviewed). IST day; guest enquiries only.
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { Card, CardBody, CardHeader, DataTable, EmptyState, type Column } from "@/components/ui/kit";

interface Block { automatic: Record<AutoKey, number>; human: Record<HumanKey, number> }
interface Row extends Block { agent_id: string | null; name: string }
interface DailyReport { date: string; agents: Row[]; total: Block; definitions: Record<string, string> }
type AutoKey = "received" | "handled" | "in_valid_stage" | "conversions";
type HumanKey = "reviewed" | "valid" | "not_valid" | "not_yet_reviewed";

const AUTO: { key: AutoKey; label: string }[] = [
  { key: "received", label: "Received" }, { key: "handled", label: "Handled" },
  { key: "in_valid_stage", label: "In a valid stage" }, { key: "conversions", label: "Bookings" },
];
const HUMAN: { key: HumanKey; label: string }[] = [
  { key: "reviewed", label: "Reviewed" }, { key: "valid", label: "Valid" },
  { key: "not_valid", label: "Not valid" }, { key: "not_yet_reviewed", label: "Not yet reviewed" },
];

export function todayIST(): string {
  return new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
}

const num = (n: number) => <span className="tabular-nums">{n}</span>;

const COLUMNS: Column<Row>[] = [
  { key: "agent", header: "Agent", cell: r => <span className="font-semibold text-[var(--haip-fg)]">{r.name}</span> },
  ...AUTO.map((c, i): Column<Row> => ({ key: c.key, header: c.label, align: "right", hideBelow: i > 1 ? "md" : undefined, cell: r => num(r.automatic[c.key]) })),
  ...HUMAN.map((c, i): Column<Row> => ({ key: `h_${c.key}`, header: c.label, align: "right", hideBelow: i > 1 ? "sm" : undefined, cell: r => num(r.human[c.key]) })),
];

function Totals({ title, items, values }: { title: string; items: { key: string; label: string }[]; values: Record<string, number> }) {
  return (
    <div className="grid gap-2">
      <h3 className="text-[12px] font-semibold uppercase tracking-wide text-[var(--haip-fg-subtle)]">{title}</h3>
      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {items.map(i => (
          <div key={i.key} className="rounded-xl border border-[var(--haip-border)] px-3 py-2">
            <dt className="text-[12.5px] text-[var(--haip-fg-muted)]">{i.label}</dt>
            <dd className="font-[family-name:var(--font-display)] text-[22px] font-semibold tabular-nums text-[var(--haip-fg)]">{values[i.key] ?? 0}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export function DailyLeadReport() {
  const [day, setDay] = useState(todayIST());
  const q = useQuery<DailyReport>({
    queryKey: ["report-daily-validation", day],
    queryFn: () => api.get("/reports/daily-validation", { params: { date: day } }).then(r => r.data),
    staleTime: 60_000,
  });
  const d = q.data;
  return (
    <Card>
      <CardHeader title="Daily lead report" description="One IST day, guest enquiries only. What the records show, apart from what a person reviewed." />
      <CardBody className="grid gap-4">
        <label className="grid w-fit gap-1 text-[13px] font-semibold text-[var(--haip-fg-2)]">Day
          <input type="date" value={day} max={todayIST()} onChange={e => e.target.value && setDay(e.target.value)}
            className="min-h-11 rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-base sm:text-sm" />
        </label>
        {q.isPending ? (
          <p className="text-sm text-[var(--haip-fg-muted)]">Loading the day…</p>
        ) : q.isError || !d ? (
          <EmptyState title="Couldn't load the report" hint="Check your connection and try again."
            action={<button type="button" onClick={() => q.refetch()} className="min-h-11 rounded-xl bg-primary px-4 text-[14px] font-semibold text-primary-foreground">Try again</button>} />
        ) : (
          <>
            <Totals title="From the records (automatic)" items={AUTO} values={d.total.automatic} />
            <Totals title="Reviewed by a person (Valid enquiry?)" items={HUMAN} values={d.total.human} />
            <DataTable<Row> columns={COLUMNS} rows={d.agents} rowKey={r => r.agent_id ?? "unassigned"}
              empty={{ title: "Nothing on this day", hint: "No enquiries arrived, were handled or were reviewed." }} />
            <p className="text-[12.5px] text-[var(--haip-fg-subtle)]">
              Handled counts each enquiry once per person; the total counts it once. Bookings = made that day from an enquiry, by its owner.
            </p>
          </>
        )}
      </CardBody>
    </Card>
  );
}
