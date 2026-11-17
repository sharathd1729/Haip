"use client";
// Home › Bookings & payments (workspace redesign Phase 2). GET /dashboard/payments (services/dashboard_tabs.py): what live
// bookings still owe (overdue first), unpaid payment links, deposits held and to give back. Every figure opens its list
// (balances: Bookings; links and deposits: Ops › Money on the matching tab).
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { Card, CardBody, CardHeader, EmptyState, Stat, StatusPill } from "@/components/ui/kit";
import { Skeleton } from "@/components/ui/skeleton";
import { lakh } from "@/components/dashboard/command/owner";

interface Money { count: number; amount: number | null }
interface Payments {
  today: string; window_days: number; money_restricted: boolean;
  balances: Money & { overdue: Money; this_week: Money; href: string;
    items: { guest: string; property: string; unassigned: boolean; check_in: string; due_date: string | null; overdue: boolean; amount: number | null; href: string }[] };
  links_unpaid: Money & { oldest: string | null; items: { amount: number | null; sent: string | null; href: string }[] };
  deposits: { held: Money; to_give_back: Money & { items: { guest: string; checked_out: string; amount: number | null; href: string }[] } };
}

const day = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "Asia/Kolkata" }) : "—");
const amount = (m: Money, restricted: boolean) => (restricted ? `${m.count}` : lakh(m.amount));
const sub = (m: Money, restricted: boolean, what: string) => (restricted ? what : `${m.count} ${what}`);

export function PaymentsTab() {
  const { data, isPending, isError, refetch } = useQuery<Payments>({
    queryKey: ["dashboard-payments"], queryFn: () => api.get("/dashboard/payments").then(r => r.data), staleTime: 60_000,
  });
  if (isPending) return <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{[0, 1, 2, 3].map(i => <Skeleton key={i} className="h-28" />)}</div>;
  if (isError || !data) {
    return <Card><EmptyState title="Bookings and payments didn't load" hint="Check your connection and try again."
      action={<button type="button" onClick={() => refetch()} className="min-h-11 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground">Try again</button>} /></Card>;
  }
  const r = data.money_restricted;
  const b = data.balances;
  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Link href={b.href} className="rounded-2xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40">
          <Stat variant={b.overdue.count ? "accent" : "default"} label="Overdue" value={amount(b.overdue, r)} hint={sub(b.overdue, r, "bookings past their due date")} />
        </Link>
        <Link href={b.href} className="rounded-2xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40">
          <Stat label="Due this week" value={amount(b.this_week, r)} hint={sub(b.this_week, r, "bookings, next 7 days")} />
        </Link>
        <Link href="/dashboard/ops/money?view=owes" className="rounded-2xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40">
          <Stat label="Payment links not paid" value={amount(data.links_unpaid, r)} hint={data.links_unpaid.oldest ? `${data.links_unpaid.count} link${data.links_unpaid.count === 1 ? "" : "s"}, oldest ${day(data.links_unpaid.oldest)}` : "none open"} />
        </Link>
        <Link href="/dashboard/ops/money?view=deposit" className="rounded-2xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40">
          <Stat label="Deposits to give back" value={amount(data.deposits.to_give_back, r)} hint={`${data.deposits.held.count} held in all`} />
        </Link>
      </div>
      {r && <p className="text-[13px] text-[var(--haip-fg-subtle)]">Amounts are hidden for your role; counts are shown.</p>}

      <Card>
        <CardHeader title="Still owing" description={`Live bookings checking in within ${data.window_days} days, overdue first`}
          actions={<Link href={b.href} className="text-sm font-semibold text-primary hover:underline">All in Bookings</Link>} />
        <CardBody>
          {b.items.length === 0 ? <p className="py-4 text-sm text-[var(--haip-fg-subtle)]">Nothing owed on upcoming bookings.</p> : (
            <ul className="divide-y divide-[var(--haip-border)]">
              {b.items.map(i => (
                <li key={i.href}>
                  <Link href={i.href} className="flex min-h-12 flex-wrap items-center gap-x-4 gap-y-1 py-2.5 hover:bg-[var(--haip-surface)]">
                    <span className="min-w-0 flex-1"><span className="block font-semibold text-[var(--haip-fg)]">{i.guest}</span>
                      <span className="block text-[13px] text-[var(--haip-fg-subtle)]">{i.unassigned ? "Unit not chosen yet" : i.property} · check-in {day(i.check_in)}</span></span>
                    {i.overdue ? <StatusPill tone="highlight">Overdue since {day(i.due_date)}</StatusPill>
                      : <span className="text-[13px] text-[var(--haip-fg-subtle)]">Due {day(i.due_date ?? i.check_in)}</span>}
                    {!r && <span className="num w-24 text-right font-semibold">{lakh(i.amount)}</span>}
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>

      {data.deposits.to_give_back.items.length > 0 && (
        <Card>
          <CardHeader title="Deposits to give back" description="Held deposits on stays that are over" />
          <CardBody>
            <ul className="divide-y divide-[var(--haip-border)]">
              {data.deposits.to_give_back.items.map(i => (
                <li key={i.href}><Link href={i.href} className="flex min-h-12 items-center gap-4 py-2.5 hover:bg-[var(--haip-surface)]">
                  <span className="min-w-0 flex-1 font-semibold">{i.guest}</span>
                  <span className="text-[13px] text-[var(--haip-fg-subtle)]">left {day(i.checked_out)}</span>
                  {!r && <span className="num w-24 text-right font-semibold">{lakh(i.amount)}</span>}
                </Link></li>
              ))}
            </ul>
          </CardBody>
        </Card>
      )}
    </div>
  );
}
