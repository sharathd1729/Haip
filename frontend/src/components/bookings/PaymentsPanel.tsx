"use client";
import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Trash2 } from "@/lib/icons";
import api from "@/lib/api";
import { cn, formatINR } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";
import {
  METHOD_LABEL, PAYMENT_STYLE, errorMessage, fmtDate,
  type BookingDetail, type PayMethod,
} from "@/lib/bookings";

const input = "w-full text-sm border border-[var(--haip-border)] rounded-lg px-2.5 py-1.5 focus:outline-none focus:ring-2 focus:ring-primary";
const METHODS: PayMethod[] = ["upi", "cash", "card", "bank_transfer", "other"];

/** Money for one booking: what is owed and the payment ledger. Collecting the balance (a Razorpay link on WhatsApp, or a
 * payment received) happens in the Collect sheet (`onCollect`); a refund or a correction is recorded here. */
export function PaymentsPanel({ booking, onChange, onCollect }: {
  booking: BookingDetail; onChange: (b: BookingDetail) => void; onCollect?: () => void;
}) {
  const { toast } = useToast();
  const f = booking.financials;
  const base = `/bookings/${booking.id}`;
  const today = new Date().toISOString().slice(0, 10);
  const [form, setForm] = useState<{ kind: "payment" | "refund"; amount: string; method: PayMethod; reference: string; paid_on: string } | null>(null);
  const { data: rzp } = useQuery<{ connected: boolean }>({
    queryKey: ["razorpay-status"],
    queryFn: () => api.get("/payments/razorpay").then(r => r.data),
    staleTime: 60_000,
    retry: false,
  });

  const save = useMutation({
    mutationFn: () => api.post(`${base}/payments`, {
      kind: form!.kind, amount: Number(form!.amount), method: form!.method,
      reference: form!.reference.trim() || undefined, paid_on: form!.paid_on,
    }),
    onSuccess: res => { onChange(res.data); setForm(null); toast({ variant: "success", title: "Saved" }); },
    onError: e => toast({ variant: "error", title: errorMessage(e, "Could not save the payment") }),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`${base}/payments/${id}`),
    onSuccess: res => onChange(res.data),
    onError: e => toast({ variant: "error", title: errorMessage(e, "Could not remove the entry") }),
  });

  const pct = f.total > 0 ? Math.min(100, Math.round((f.paid / f.total) * 100)) : 0;

  return (
    <section className="haip-card">
      <div className="haip-card-head">
        <h2 className="haip-card-title">Money</h2>
        <span className={cn("ml-auto inline-flex rounded-full border px-2 py-0.5 text-[11px] font-semibold", PAYMENT_STYLE[f.payment_status].cls)}>
          {PAYMENT_STYLE[f.payment_status].label}
        </span>
      </div>
      <div className="p-4 space-y-4">
        <dl className="text-sm space-y-1.5">
          <div className="flex justify-between"><dt className="text-[var(--haip-fg-subtle)]">Stay</dt><dd className="tabular-nums">{formatINR(f.stay_charge)}</dd></div>
          <div className="flex justify-between"><dt className="text-[var(--haip-fg-subtle)]">Add-ons</dt><dd className="tabular-nums">{formatINR(f.addons_total)}</dd></div>
          <div className="flex justify-between font-semibold border-t border-[var(--haip-border)] pt-1.5"><dt>Total</dt><dd className="tabular-nums">{formatINR(f.total)}</dd></div>
          <div className="flex justify-between text-emerald-700"><dt>Received</dt><dd className="tabular-nums">{formatINR(f.paid)}</dd></div>
          <div className={cn("flex justify-between font-semibold", f.outstanding > 0 ? "text-red-600" : "text-[var(--haip-fg-subtle)]")}>
            <dt>Still due</dt><dd className="tabular-nums">{formatINR(f.outstanding)}</dd>
          </div>
        </dl>
        <div className="h-1.5 rounded-full bg-[var(--haip-status-neutral-bg)] overflow-hidden" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label="Share of total received">
          <div className="h-full bg-emerald-500 transition-all" style={{ width: `${pct}%` }} />
        </div>

        {booking.payments.length > 0 && (
          <ul className="divide-y divide-[var(--haip-border)] text-sm">
            {booking.payments.map(p => (
              <li key={p.id} className="flex items-center gap-2 py-2">
                <div className="min-w-0 flex-1">
                  <p className="font-medium text-[var(--haip-fg)]">
                    {p.kind === "refund" ? "Refund" : "Payment"} · {METHOD_LABEL[p.method] ?? p.method}
                  </p>
                  <p className="text-xs text-[var(--haip-fg-subtle)] truncate">{fmtDate(p.paid_on)}{p.reference ? ` · ${p.reference}` : ""}</p>
                </div>
                <span className={cn("tabular-nums font-semibold", p.kind === "refund" ? "text-red-600" : "text-[var(--haip-fg)]")}>
                  {p.kind === "refund" ? "-" : ""}{formatINR(p.amount)}
                </span>
                {!p.via_gateway && (
                  <button
                    aria-label="Remove this entry"
                    onClick={() => { if (confirm("Remove this entry? It will be noted in the activity log.")) remove.mutate(p.id); }}
                    className="w-7 h-7 rounded-lg flex items-center justify-center text-[var(--haip-fg-subtle)]/70 hover:text-red-500 hover:bg-red-50"
                  >
                    <Trash2 size={13} />
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}

        {form ? (
          <div className="space-y-2.5 rounded-xl border border-[var(--haip-border)] p-3">
            <div className="flex gap-1 p-0.5 bg-[var(--haip-status-neutral-bg)] rounded-lg w-fit">
              {(["payment", "refund"] as const).map(k => (
                <button key={k} onClick={() => setForm(s => s && { ...s, kind: k })}
                  className={cn("px-3 py-1 rounded-md text-xs font-semibold", form.kind === k ? "bg-white shadow-sm text-[var(--haip-fg)]" : "text-[var(--haip-fg-subtle)]")}>
                  {k === "payment" ? "Payment received" : "Refund"}
                </button>
              ))}
            </div>
            <div className="grid grid-cols-2 gap-2">
              <label className="text-xs text-[var(--haip-fg-subtle)]">Amount (₹)
                <input className={cn(input, "mt-1")} inputMode="decimal" autoFocus value={form.amount}
                  onChange={e => setForm(s => s && { ...s, amount: e.target.value.replace(/[^0-9.]/g, "") })} />
              </label>
              <label className="text-xs text-[var(--haip-fg-subtle)]">Date
                <input className={cn(input, "mt-1")} type="date" max={today} value={form.paid_on} onChange={e => setForm(s => s && { ...s, paid_on: e.target.value })} />
              </label>
              <label className="text-xs text-[var(--haip-fg-subtle)]">Method
                <select className={cn(input, "mt-1")} value={form.method} onChange={e => setForm(s => s && { ...s, method: e.target.value as PayMethod })}>
                  {METHODS.map(m => <option key={m} value={m}>{METHOD_LABEL[m]}</option>)}
                </select>
              </label>
              <label className="text-xs text-[var(--haip-fg-subtle)]">Reference (optional)
                <input className={cn(input, "mt-1")} placeholder="UTR / receipt no." value={form.reference} onChange={e => setForm(s => s && { ...s, reference: e.target.value })} />
              </label>
            </div>
            <div className="flex gap-2">
              <button onClick={() => setForm(null)} className="flex-1 py-2 border border-[var(--haip-border)] rounded-lg text-xs text-[var(--haip-fg-muted)] hover:bg-[var(--haip-surface)]">Cancel</button>
              <button
                onClick={() => save.mutate()}
                disabled={!(Number(form.amount) > 0) || save.isPending}
                className="flex-1 py-2 bg-primary hover:bg-primary disabled:opacity-40 text-white font-semibold rounded-lg text-xs"
              >
                {save.isPending ? "Saving..." : form.kind === "refund" ? "Record refund" : "Record payment"}
              </button>
            </div>
          </div>
        ) : (
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => setForm({ kind: "payment", amount: f.outstanding > 0 ? String(f.outstanding) : "", method: "upi", reference: "", paid_on: today })}
              className="text-xs font-semibold bg-primary text-white px-3 py-2 rounded-lg hover:bg-primary"
            >
              Record payment
            </button>
            {f.paid > 0 && (
              <button onClick={() => setForm({ kind: "refund", amount: "", method: "upi", reference: "", paid_on: today })}
                className="text-xs font-semibold border border-[var(--haip-border)] text-[var(--haip-fg-2)] px-3 py-2 rounded-lg hover:bg-[var(--haip-surface)]">
                Record refund
              </button>
            )}
            {f.outstanding > 0 && onCollect && booking.status !== "cancelled" && (
              <button onClick={onCollect}
                className="min-h-9 pointer-coarse:min-h-11 text-xs font-semibold border border-[var(--haip-border)] text-[var(--haip-fg-2)] px-3 py-2 rounded-lg hover:bg-[var(--haip-surface)]">
                Collect {formatINR(f.outstanding)}
              </button>
            )}
          </div>
        )}

        {f.outstanding > 0 && rzp?.connected === false && (
          <p className="text-xs text-[var(--haip-fg-subtle)]">
            Collect online with Razorpay. <Link href="/dashboard/settings/payments" className="text-primary font-medium hover:underline">Connect your account</Link>
          </p>
        )}

        {booking.payment_links.filter(l => l.status === "created").slice(0, 1).map(l => (
          <p key={l.id} className="text-xs text-[var(--haip-fg-subtle)]">
            A payment link for <span className="tabular-nums">{formatINR(l.amount)}</span> is open. The payment is recorded here automatically when the guest pays.
          </p>
        ))}
      </div>
    </section>
  );
}
