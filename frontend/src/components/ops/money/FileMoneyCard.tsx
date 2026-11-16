"use client";
// The ops file's Money card (workspace redesign Phase 4, mockup C1): what is still to collect with a paid bar and the two
// actions, the payment plan, and every dated line (payments, refunds, links, extras, expenses) from
// GET /ops/files/{id}/money (ops_money_board.stay_ledger). The totals come from the file's own `account`; each file keeps
// its breakdown rows and its own buttons (deposit, check-out, report) as children. Anchor #money (Ops › Money links here).
import { useState, type ReactNode } from "react";
import { useSession } from "next-auth/react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { rupees } from "@/lib/ops";
import { Card, CardBody, CardHeader, StatusPill } from "@/components/ui/kit";
import { Skeleton } from "@/components/ui/skeleton";
import { MONEY_EDIT_ROLES, RecordPaymentDrawer, usePayLink } from "./MoneyActions";

interface Line { on: string; kind: "payment" | "refund" | "link" | "extra" | "expense"; amount: number; sign: number; text: string; detail: string | null }
interface Ledger {
  booking_id: string; next_due: { amount: number; due_date: string; overdue: boolean; label: string } | null;
  schedule: { id: string; label: string; amount: number; due_date: string; paid: number; status: string }[]; lines: Line[];
}
const short = (iso: string) => new Date(`${iso.slice(0, 10)}T00:00:00Z`).toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "UTC" });
const TONE: Record<string, "success" | "warning" | "danger" | "neutral"> = { paid: "success", partial: "warning", due: "warning", overdue: "danger", cancelled: "neutral" };
const WORD: Record<string, string> = { paid: "Paid", partial: "Part paid", due: "Due", overdue: "Overdue", cancelled: "Cancelled" };

export function FileMoneyCard({ fileId, guest, total, paid, outstanding, word, headerAction, footer, children }: {
  fileId: string; guest: string; total: number; paid: number; outstanding: number; word: string;
  headerAction?: ReactNode; footer?: ReactNode; children?: ReactNode;
}) {
  const qc = useQueryClient();
  const role = (useSession().data?.user as { role?: string } | undefined)?.role ?? "";
  const canEdit = MONEY_EDIT_ROLES.includes(role);  // the booking's payment endpoints allow these roles only
  const [paying, setPaying] = useState(false);
  const { data, isPending, isError } = useQuery<Ledger>({
    queryKey: ["ops-file-money", fileId], queryFn: () => api.get(`/ops/files/${fileId}/money`).then(r => r.data), staleTime: 30_000,
  });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["ops-file-money", fileId] });
    qc.invalidateQueries({ queryKey: ["ops-file", fileId] });
    qc.invalidateQueries({ queryKey: ["ops-money"] });
  };
  const link = usePayLink(refresh);
  const owing = outstanding > 0.005;
  const share = total > 0 ? Math.min(1, paid / total) : 0;
  const due = data?.next_due;

  return (
    <Card id="money" className="scroll-mt-24">
      <CardHeader title="Money" description={`This ${word} so far, GST included`} actions={headerAction} />
      <CardBody className="flex flex-col gap-4 px-4 pb-4">
        <div className="flex flex-col gap-3 rounded-2xl bg-[var(--haip-surface)] p-4">
          <div className="flex items-start justify-between gap-3">
            <div className="flex flex-col">
              <span className="text-[13px] text-[var(--haip-fg-subtle)]">{owing ? "Still to collect" : total > 0 ? "Paid in full" : "No amount on the booking yet"}</span>
              <span className={`num font-[family-name:var(--font-display)] text-[32px] font-semibold leading-tight ${owing && due?.overdue ? "text-[var(--haip-status-danger-fg)]" : "text-[var(--haip-fg)]"}`}>
                {owing ? rupees(outstanding) : rupees(total)}
              </span>
              {owing && due && <span className={`text-[13px] font-semibold ${due.overdue ? "text-[var(--haip-status-danger-fg)]" : "text-[var(--haip-fg-muted)]"}`}>
                {due.overdue ? "Overdue since" : "Next due"} {short(due.due_date)}: {due.label} {rupees(due.amount)}</span>}
            </div>
          </div>
          {total > 0 && (
            <div className="flex flex-col gap-1.5">
              <svg width="100%" height="10" role="img" aria-label={`${Math.round(share * 100)}% paid`}>
                <rect width="100%" height="10" rx="5" fill="var(--haip-border)" />
                <rect width={`${share * 100}%`} height="10" rx="5" fill="var(--primary)" />
              </svg>
              <span className="text-[13px] text-[var(--haip-fg-muted)]">Paid {rupees(paid)} of {rupees(total)}</span>
            </div>
          )}
          {canEdit && owing && data && (
            <div className="grid grid-cols-2 gap-2">
              <button type="button" className="haip-btn-primary min-h-12 whitespace-nowrap px-2 text-[15px]" onClick={() => setPaying(true)}>Record payment</button>
              <button type="button" className="haip-btn-secondary min-h-12 whitespace-nowrap px-2 text-[15px]" disabled={link.isPending} onClick={() => link.mutate(data.booking_id)}>
                {link.isPending ? "Sending…" : "Send pay link"}</button>
            </div>
          )}
        </div>

        {isPending ? <Skeleton className="h-24" /> : isError || !data ? (
          <p className="text-[14px] text-[var(--haip-fg-subtle)]">The payment lines didn&apos;t load. The totals below are current.</p>
        ) : (
          <>
            {data.schedule.length > 0 && (
              <div className="flex flex-col gap-2">
                <span className="text-[14px] font-semibold">Plan</span>
                {data.schedule.map(s => (
                  <div key={s.id} className="flex min-h-10 items-center gap-3 text-[14px]">
                    <span className="flex-1">{s.label}, {short(s.due_date)}</span>
                    <span className="num">{rupees(s.amount)}</span>
                    <StatusPill tone={TONE[s.status] ?? "neutral"}>{WORD[s.status] ?? s.status}</StatusPill>
                  </div>
                ))}
              </div>
            )}
            <div className="flex flex-col">
              <span className="pb-1 text-[14px] font-semibold">Every rupee</span>
              {data.lines.length === 0 ? <p className="text-[14px] text-[var(--haip-fg-subtle)]">No payments, extras or expenses yet.</p> : data.lines.map((l, i) => (
                <div key={`${l.on}-${i}`} className="grid grid-cols-[56px_1fr_auto] items-center gap-x-3 border-t border-[var(--haip-border)] py-2.5 text-[14px]">
                  <span className="text-[13px] text-[var(--haip-fg-subtle)]">{short(l.on)}</span>
                  <span className="min-w-0">{l.text}{l.detail && <span className="block truncate text-[12.5px] text-[var(--haip-fg-subtle)]">{l.detail}</span>}</span>
                  <span className={`num font-semibold ${l.sign > 0 ? "text-[var(--haip-status-success-fg)]" : l.sign < 0 ? "text-[var(--haip-status-danger-fg)]" : "text-[var(--haip-fg-muted)]"}`}>
                    {l.sign > 0 ? "+ " : l.sign < 0 ? "− " : ""}{rupees(l.amount)}</span>
                </div>
              ))}
            </div>
          </>
        )}

        {children && <details className="group rounded-xl border border-[var(--haip-border)] px-3">
          <summary className="flex min-h-11 cursor-pointer items-center text-[14px] font-semibold">Breakdown and account</summary>
          <div className="pb-2">{children}</div>
        </details>}
        {footer}
      </CardBody>
      {paying && data && <RecordPaymentDrawer bookingId={data.booking_id} guest={guest} balance={outstanding} open
        onOpenChange={o => { if (!o) setPaying(false); }} onDone={refresh} />}
    </Card>
  );
}
