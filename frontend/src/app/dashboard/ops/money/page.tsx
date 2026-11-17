"use client";
// Ops › Money (workspace redesign Phase 4, mockup C2): every stay overlapping the month with what it owes, the period's
// numbers (overdue, due in 7 days, collected, deposits, spent on stays), and one action per row. GET /ops/money?month=
// (services/ops_money_board.board; amounts need bookings.read, else counts only). Rows open the ops file (or the booking).
import { useState } from "react";
import Link from "next/link";
import { useSession } from "next-auth/react";
import { useSearchParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { rupees } from "@/lib/ops";
import { Card, EmptyState, PageHeader, StatusPill } from "@/components/ui/kit";
import { Skeleton } from "@/components/ui/skeleton";
import { OpsNav } from "@/components/ops/OpsNav";
import { MONEY_EDIT_ROLES, RecordPaymentDrawer, usePayLink } from "@/components/ops/money/MoneyActions";

interface Row {
  booking_id: string; file_id: string | null; guest: string; property: string; check_in: string; check_out: string; nights: number;
  status: string; total: number | null; paid: number | null; balance: number | null; paid_share: number | null; owing: boolean;
  due_date: string | null; overdue: boolean; deposit: { status: string; amount: number | null; settle: boolean } | null;
  link: { status: string; amount: number | null; sent: string | null } | null;
}
interface Board {
  today: string; from: string; to: string; money_restricted: boolean;
  totals: {
    overdue: { count: number; amount: number | null }; due_week: { count: number; amount: number | null };
    collected: { count: number; amount: number | null; refunds: number; refunded: number | null };
    deposits: { held: number; amount: number | null; to_give_back: number }; spent: { amount: number | null; top: string[] };
  };
  rows: Row[];
  payments: { on: string; kind: string; amount: number | null; method: string; guest: string; booking_id: string }[];
}
type View = "owes" | "deposit" | "paid" | "payments";

const day = (iso: string) => new Date(`${iso.slice(0, 10)}T00:00:00Z`).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });
const short = (iso: string) => new Date(`${iso.slice(0, 10)}T00:00:00Z`).toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "UTC" });
const money = (v: number | null, restricted: boolean) => (restricted || v == null ? "—" : rupees(v));
const monthKey = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
const monthLabel = (key: string) => new Date(`${key}-01T00:00:00Z`).toLocaleDateString("en-IN", { month: "long", year: "numeric", timeZone: "UTC" });

function dueText(r: Row) {
  if (!r.owing) return null;
  if (r.overdue) return <StatusPill tone="danger">Overdue since {short(r.due_date ?? r.check_in)}</StatusPill>;
  if (r.link?.status === "created") return <StatusPill tone="warning">Link sent · due {short(r.due_date ?? r.check_in)}</StatusPill>;
  return <StatusPill tone="neutral">Due {short(r.due_date ?? r.check_in)}</StatusPill>;
}

export default function OpsMoneyPage() {
  const qc = useQueryClient();
  const role = (useSession().data?.user as { role?: string } | undefined)?.role ?? "";
  const canEdit = MONEY_EDIT_ROLES.includes(role);
  const now = new Date();
  const months = [-2, -1, 0, 1, 2].map(n => monthKey(new Date(now.getFullYear(), now.getMonth() + n, 1)));
  const [month, setMonth] = useState(months[2]);
  const asked = useSearchParams().get("view");  // dashboard tiles open a tab: ?view=owes|deposit|paid|payments
  const [view, setView] = useState<View>(asked === "deposit" || asked === "paid" || asked === "payments" ? asked : "owes");
  const [paying, setPaying] = useState<Row | null>(null);
  const { data, isPending, isError, refetch } = useQuery<Board>({
    queryKey: ["ops-money", month], queryFn: () => api.get("/ops/money", { params: { month } }).then(r => r.data), staleTime: 30_000,
  });
  const refresh = () => qc.invalidateQueries({ queryKey: ["ops-money"] });
  const link = usePayLink(refresh);

  const r = data?.money_restricted ?? false;
  const rows = (data?.rows ?? []).filter(x => view === "owes" ? x.owing : view === "deposit" ? !!x.deposit?.settle : view === "paid" ? !x.owing && (x.total ?? 1) > 0 : true);
  const counts = data ? {
    owes: data.rows.filter(x => x.owing).length, deposit: data.rows.filter(x => x.deposit?.settle).length,
    paid: data.rows.filter(x => !x.owing && (x.total ?? 1) > 0).length, payments: data.payments.length,
  } : null;
  const tiles = data ? [
    { label: "Overdue", value: money(data.totals.overdue.amount, r), sub: `${data.totals.overdue.count} stay${data.totals.overdue.count === 1 ? "" : "s"} past the due date`, hot: data.totals.overdue.count > 0 },
    { label: "To collect in 7 days", value: money(data.totals.due_week.amount, r), sub: `${data.totals.due_week.count} stay${data.totals.due_week.count === 1 ? "" : "s"}` },
    { label: `Collected in ${monthLabel(month).split(" ")[0]}`, value: money(data.totals.collected.amount, r), sub: `${data.totals.collected.count} payments${data.totals.collected.refunds ? ` · ${data.totals.collected.refunds} refunds` : ""}` },
    { label: "Deposits held", value: money(data.totals.deposits.amount, r), sub: data.totals.deposits.to_give_back ? `${data.totals.deposits.to_give_back} to give back` : `${data.totals.deposits.held} held` },
    { label: "Spent on stays", value: money(data.totals.spent.amount, r), sub: data.totals.spent.top.join(", ") || "No expenses" },
  ] : [];

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-5 p-4 sm:p-6">
      <PageHeader title="Ops money" subtitle={`Stays checking in or out in ${monthLabel(month)}`} />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <OpsNav />
        <label className="flex items-center gap-2 text-[14px] text-[var(--haip-fg-subtle)]">
          <span className="sr-only sm:not-sr-only">Month</span>
          <select value={month} onChange={e => setMonth(e.target.value)} className="min-h-11 rounded-full border border-[var(--haip-border)] bg-[var(--haip-card)] px-4 text-[16px] font-semibold text-[var(--haip-fg)]">
            {months.map(m => <option key={m} value={m}>{monthLabel(m)}</option>)}
          </select>
        </label>
      </div>

      {isPending ? (
        <div className="flex flex-col gap-3" aria-busy="true"><div className="grid grid-cols-2 gap-3 lg:grid-cols-5">{[0, 1, 2, 3, 4].map(i => <Skeleton key={i} className="h-24" />)}</div><Skeleton className="h-64" /></div>
      ) : isError || !data ? (
        <Card><EmptyState title="Money didn't load" hint="Check your connection and try again."
          action={<button type="button" className="haip-btn-primary min-h-12" onClick={() => refetch()}>Try again</button>} /></Card>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
            {tiles.map(t => (
              <div key={t.label} className={`flex flex-col gap-1 rounded-2xl border bg-[var(--haip-card)] p-4 ${t.hot ? "border-[var(--haip-accent)]" : "border-[var(--haip-border)]"}`}>
                <span className="text-[13px] text-[var(--haip-fg-subtle)]">{t.label}</span>
                <span className="num font-[family-name:var(--font-display)] text-[24px] font-semibold text-[var(--haip-fg)]">{t.value}</span>
                <span className="text-[13px] text-[var(--haip-fg-subtle)]">{t.sub}</span>
              </div>
            ))}
          </div>
          {r && <p className="text-[13px] text-[var(--haip-fg-subtle)]">Amounts are hidden for your role; counts are shown.</p>}

          <Card className="overflow-hidden">
            <div role="tablist" aria-label="Which stays" className="flex flex-wrap gap-2 border-b border-[var(--haip-border)] p-3">
              {([["owes", "Owes money"], ["deposit", "Deposit to settle"], ["paid", "Paid in full"], ["payments", "All payments"]] as [View, string][]).map(([k, l]) => (
                <button key={k} type="button" role="tab" aria-selected={view === k} onClick={() => setView(k)}
                  className={`min-h-11 rounded-full px-4 text-[14px] ${view === k ? "bg-[var(--haip-fg)] font-semibold text-[var(--haip-card)]" : "border border-[var(--haip-border)] text-[var(--haip-fg)]"}`}>
                  {l} · {counts?.[k] ?? 0}
                </button>
              ))}
            </div>

            {view === "payments" ? (
              data.payments.length === 0 ? <EmptyState title="No payments this month" hint="Payments recorded on bookings show here." /> : (
                <ul className="divide-y divide-[var(--haip-border)]">
                  {data.payments.map((p, i) => (
                    <li key={`${p.booking_id}-${i}`}>
                      <Link href={`/dashboard/bookings/${p.booking_id}`} className="flex min-h-14 items-center gap-4 px-4 py-2 hover:bg-[var(--haip-surface)]">
                        <span className="w-16 text-[13px] text-[var(--haip-fg-subtle)]">{short(p.on)}</span>
                        <span className="min-w-0 flex-1"><span className="block font-semibold text-[var(--haip-fg)]">{p.guest}</span>
                          <span className="block text-[13px] text-[var(--haip-fg-subtle)]">{p.kind === "refund" ? "Refund" : "Payment"} · {p.method}</span></span>
                        <span className={`num font-semibold ${p.kind === "refund" ? "text-[var(--haip-status-danger-fg)]" : "text-[var(--haip-status-success-fg)]"}`}>
                          {p.kind === "refund" ? "− " : "+ "}{money(p.amount, r)}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )
            ) : rows.length === 0 ? (
              <EmptyState title={view === "owes" ? "Nobody owes money" : view === "deposit" ? "No deposits to settle" : "No stays paid in full yet"}
                hint={`For stays checking in or out in ${monthLabel(month)}.`} />
            ) : (
              <ul className="divide-y divide-[var(--haip-border)]">
                {rows.map(x => {
                  const href = x.file_id ? `/dashboard/ops/files/${x.file_id}#money` : `/dashboard/bookings/${x.booking_id}`;
                  return (
                    <li key={x.booking_id} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
                      <Link href={href} className="min-w-[180px] flex-1">
                        <span className="block font-semibold text-[var(--haip-fg)] hover:underline">{x.guest}</span>
                        <span className="block text-[13px] text-[var(--haip-fg-subtle)]">{x.property} · {day(x.check_in)} · {x.nights} night{x.nights === 1 ? "" : "s"}</span>
                      </Link>
                      <span className="flex w-28 flex-col gap-1">
                        <span className="h-2 overflow-hidden rounded-full bg-[var(--haip-surface)]">
                          <svg width="100%" height="8" aria-hidden><rect width={`${Math.round((x.paid_share ?? 0) * 100)}%`} height="8" fill="var(--primary)" /></svg>
                        </span>
                        <span className="num text-[12px] text-[var(--haip-fg-subtle)]">{r ? `${Math.round((x.paid_share ?? 0) * 100)}% paid` : `${money(x.paid, r)} of ${money(x.total, r)}`}</span>
                      </span>
                      <span className="num w-24 text-right font-semibold text-[var(--haip-fg)]">{x.owing ? money(x.balance, r) : "Paid"}</span>
                      <span className="w-48">{view === "deposit" && x.deposit ? <StatusPill tone="warning">Deposit {money(x.deposit.amount, r)} to settle</StatusPill> : dueText(x)}</span>
                      <span className="ml-auto flex gap-2">
                        {view === "deposit" ? <Link href={href} className="haip-btn-secondary inline-flex min-h-11 items-center px-4">Decide deposit</Link>
                          : canEdit && x.owing && (x.link?.status === "created"
                            ? <button type="button" className="haip-btn-secondary min-h-11 px-4" onClick={() => setPaying(x)}>Record payment</button>
                            : <button type="button" className="haip-btn-secondary min-h-11 px-4" disabled={link.isPending && link.variables === x.booking_id}
                                onClick={() => link.mutate(x.booking_id)}>{link.isPending && link.variables === x.booking_id ? "Sending…" : "Send pay link"}</button>)}
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
          </Card>
        </>
      )}
      {paying && <RecordPaymentDrawer key={paying.booking_id} bookingId={paying.booking_id} guest={paying.guest} balance={paying.balance}
        open onOpenChange={o => { if (!o) setPaying(null); }} onDone={refresh} />}
    </div>
  );
}
