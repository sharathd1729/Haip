"use client";
// Reports > By check-in month (checkin_month_report, KPI D-30). GET /reports/checkin-months (owner/manager + analytics.read):
// per check-in month, guest enquiries, valid (a person's review else the valid-lead rule), won, lost (+ top reasons), open
// and booked revenue (revenue.read only; otherwise "Restricted", never 0). Undated leads sit in their own row.
// Phone first: one card per month with a won/lost/open bar; no wide table.
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { Card, CardBody, CardHeader, EmptyState } from "@/components/ui/kit";

interface Row {
  month: string | null; label: string; enquiries: number; valid: number; won: number; lost: number; open: number;
  top_lost_reasons: { reason: string; label: string; count: number }[]; booked_revenue?: number | { restricted: true };
}
interface Report { start: string; months: number; rows: Row[]; no_date: Row; skipped: number; money: boolean; basis: string }

const inr = (v: number) => `₹${Math.round(v).toLocaleString("en-IN")}`;

function Bar({ r }: { r: Row }) {
  const total = Math.max(1, r.won + r.lost + r.open);
  const parts = [
    { n: r.won, cls: "fill-[var(--haip-status-success-fg)]" },
    { n: r.lost, cls: "fill-[var(--haip-status-danger-fg)]" },
    { n: r.open, cls: "fill-[var(--haip-border-strong)]" },
  ];
  let x = 0;
  return (
    <svg viewBox="0 0 100 10" preserveAspectRatio="none" className="h-2.5 w-full overflow-hidden rounded-full bg-[var(--haip-surface)]" aria-hidden>
      {parts.map((p, i) => { const w = (p.n / total) * 100; const el = <rect key={i} x={x} y={0} width={w} height={10} className={p.cls} />; x += w; return el; })}
    </svg>
  );
}

function MonthCard({ r }: { r: Row }) {
  const money = r.booked_revenue;
  return (
    <li className="grid gap-1.5 rounded-xl border border-[var(--haip-border)] px-3 py-2.5">
      <span className="flex flex-wrap items-baseline justify-between gap-2">
        <strong className="text-[14.5px] text-[var(--haip-fg)]">{r.label}</strong>
        {money !== undefined && (
          <span className="text-[13px] tabular-nums text-[var(--haip-fg-2)]">
            {typeof money === "number" ? `${inr(money)} booked` : "Revenue restricted"}
          </span>
        )}
      </span>
      <span className="text-[13px] text-[var(--haip-fg-2)]">
        {r.enquiries} enquiries · {r.valid} valid · <span className="text-[var(--haip-status-success-fg)]">{r.won} won</span> ·{" "}
        <span className="text-[var(--haip-status-danger-fg)]">{r.lost} lost</span> · {r.open} open
      </span>
      {r.enquiries > 0 && <Bar r={r} />}
      {r.top_lost_reasons.length > 0 && (
        <span className="text-[12.5px] text-[var(--haip-fg-subtle)]">Lost: {r.top_lost_reasons.map(x => `${x.label} ${x.count}`).join(" · ")}</span>
      )}
    </li>
  );
}

export function CheckinMonths() {
  const q = useQuery<Report>({
    queryKey: ["report-checkin-months"], queryFn: () => api.get("/reports/checkin-months", { params: { months: 6 } }).then(r => r.data),
    staleTime: 5 * 60_000,
  });
  const r = q.data;
  return (
    <Card>
      <CardHeader title="By check-in month" description="Guest enquiries grouped by the month they want to travel. Won / lost = their stage now." />
      <CardBody className="grid gap-3">
        {q.isPending ? (
          <p className="text-sm text-[var(--haip-fg-muted)]">Loading…</p>
        ) : q.isError || !r ? (
          <EmptyState title="Couldn't load the report" hint="Check your connection and try again."
            action={<button type="button" onClick={() => q.refetch()} className="min-h-11 rounded-xl bg-primary px-4 text-[14px] font-semibold text-primary-foreground">Try again</button>} />
        ) : r.rows.every(x => x.enquiries === 0) && r.no_date.enquiries === 0 ? (
          <EmptyState title="No enquiries for these months" />
        ) : (
          <>
            <ul className="grid gap-2 sm:grid-cols-2">
              {r.rows.map(x => <MonthCard key={x.month} r={x} />)}
              <MonthCard r={r.no_date} />
            </ul>
            <p className="text-[12.5px] text-[var(--haip-fg-subtle)]">
              {r.basis}{r.skipped ? ` ${r.skipped} with a check-in we could not read are not counted.` : ""}
            </p>
          </>
        )}
      </CardBody>
    </Card>
  );
}
