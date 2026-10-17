"use client";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import api from "@/lib/api";
import { cn, formatINR } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";
import { METHOD_LABEL, errorMessage, fmtDate, type BookingDetail, type Deposit, type PayMethod } from "@/lib/bookings";

const input = "w-full text-sm border border-[var(--haip-border)] rounded-lg px-2.5 py-1.5 focus:outline-none focus:ring-2 focus:ring-primary";
const METHODS: PayMethod[] = ["upi", "cash", "card", "bank_transfer", "other"];

const STATUS: Record<Deposit["status"], { label: string; cls: string }> = {
  pending:   { label: "Not collected", cls: "bg-[var(--haip-status-neutral-bg)] text-[var(--haip-fg-muted)] border-[var(--haip-border)]" },
  held:      { label: "Held",          cls: "bg-blue-50 text-blue-700 border-blue-100" },
  released:  { label: "Released",      cls: "bg-emerald-50 text-emerald-700 border-emerald-100" },
  forfeited: { label: "Kept",          cls: "bg-red-50 text-red-700 border-red-100" },
};

/** Refundable security deposit. Held apart from the booking total and never counted as revenue. */
export function DepositPanel({ booking, onChange }: { booking: BookingDetail; onChange: (b: BookingDetail) => void }) {
  const { toast } = useToast();
  const dep = booking.deposit;
  const [form, setForm] = useState<{ amount: string; status: Deposit["status"]; deducted: string; method: PayMethod; notes: string } | null>(null);

  const save = useMutation({
    mutationFn: () => api.put(`/bookings/${booking.id}/deposit`, {
      amount: Number(form!.amount), status: form!.status,
      deducted: form!.status === "released" ? Number(form!.deducted) || 0 : 0,
      method: form!.status === "pending" ? undefined : form!.method, notes: form!.notes.trim() || undefined,
    }),
    onSuccess: res => { onChange(res.data); setForm(null); toast({ variant: "success", title: "Deposit saved" }); },
    onError: e => toast({ variant: "error", title: errorMessage(e, "Could not save the deposit") }),
  });
  const remove = useMutation({
    mutationFn: () => api.delete(`/bookings/${booking.id}/deposit`),
    onSuccess: res => { onChange(res.data); setForm(null); },
    onError: e => toast({ variant: "error", title: errorMessage(e, "Could not remove the deposit") }),
  });

  const open = () => setForm({
    amount: dep ? String(dep.amount) : "", status: dep?.status ?? "pending", deducted: dep?.deducted ? String(dep.deducted) : "",
    method: dep?.method ?? "upi", notes: dep?.notes ?? "",
  });

  return (
    <section className="haip-card">
      <div className="haip-card-head">
        <h2 className="haip-card-title">Security deposit</h2>
        {dep && !form && <span className={cn("ml-auto inline-flex rounded-full border px-2 py-0.5 text-[11px] font-semibold", STATUS[dep.status].cls)}>{STATUS[dep.status].label}</span>}
      </div>
      <div className="p-4 space-y-3 text-sm">
        {!dep && !form && (
          <>
            <p className="text-[var(--haip-fg-subtle)]">No deposit on this booking. A deposit is held separately and does not count as revenue.</p>
            <button onClick={open} className="text-xs font-semibold border border-[var(--haip-border)] px-3 py-2 rounded-lg hover:bg-[var(--haip-surface)]">Add deposit</button>
          </>
        )}

        {dep && !form && (
          <>
            <dl className="space-y-1.5">
              <div className="flex justify-between"><dt className="text-[var(--haip-fg-subtle)]">Deposit</dt><dd className="tabular-nums font-semibold">{formatINR(dep.amount)}</dd></div>
              {dep.status === "released" && (
                <>
                  {dep.deducted > 0 && <div className="flex justify-between text-red-600"><dt>Kept for damage</dt><dd className="tabular-nums">{formatINR(dep.deducted)}</dd></div>}
                  <div className="flex justify-between text-emerald-700"><dt>Returned to guest</dt><dd className="tabular-nums">{formatINR(dep.refundable)}</dd></div>
                </>
              )}
              {dep.method && <div className="flex justify-between"><dt className="text-[var(--haip-fg-subtle)]">Method</dt><dd>{METHOD_LABEL[dep.method]}</dd></div>}
              {dep.collected_on && <div className="flex justify-between"><dt className="text-[var(--haip-fg-subtle)]">Collected</dt><dd>{fmtDate(dep.collected_on)}</dd></div>}
              {dep.resolved_on && <div className="flex justify-between"><dt className="text-[var(--haip-fg-subtle)]">Settled</dt><dd>{fmtDate(dep.resolved_on)}</dd></div>}
            </dl>
            {dep.notes && <p className="text-xs text-[var(--haip-fg-subtle)]">{dep.notes}</p>}
            <div className="flex gap-2">
              <button onClick={open} className="text-xs font-semibold border border-[var(--haip-border)] px-3 py-1.5 rounded-lg hover:bg-[var(--haip-surface)]">Update</button>
              <button onClick={() => { if (confirm("Remove the deposit record?")) remove.mutate(); }} className="text-xs font-semibold text-red-700 px-3 py-1.5 rounded-lg hover:bg-red-50">Remove</button>
            </div>
          </>
        )}

        {form && (
          <div className="space-y-2.5">
            <div className="grid grid-cols-2 gap-2">
              <label className="text-xs text-[var(--haip-fg-subtle)]">Amount (₹)
                <input className={cn(input, "mt-1")} inputMode="decimal" autoFocus value={form.amount} onChange={e => setForm(f => f && { ...f, amount: e.target.value.replace(/[^0-9.]/g, "") })} />
              </label>
              <label className="text-xs text-[var(--haip-fg-subtle)]">Status
                <select className={cn(input, "mt-1")} value={form.status} onChange={e => setForm(f => f && { ...f, status: e.target.value as Deposit["status"] })}>
                  <option value="pending">Not collected</option>
                  <option value="held">Held</option>
                  <option value="released">Released to guest</option>
                  <option value="forfeited">Kept in full</option>
                </select>
              </label>
              {form.status !== "pending" && (
                <label className="text-xs text-[var(--haip-fg-subtle)]">Method
                  <select className={cn(input, "mt-1")} value={form.method} onChange={e => setForm(f => f && { ...f, method: e.target.value as PayMethod })}>
                    {METHODS.map(m => <option key={m} value={m}>{METHOD_LABEL[m]}</option>)}
                  </select>
                </label>
              )}
              {form.status === "released" && (
                <label className="text-xs text-[var(--haip-fg-subtle)]">Kept for damage (₹)
                  <input className={cn(input, "mt-1")} inputMode="decimal" placeholder="0" value={form.deducted} onChange={e => setForm(f => f && { ...f, deducted: e.target.value.replace(/[^0-9.]/g, "") })} />
                </label>
              )}
            </div>
            <label className="block text-xs text-[var(--haip-fg-subtle)]">Notes
              <input className={cn(input, "mt-1")} value={form.notes} onChange={e => setForm(f => f && { ...f, notes: e.target.value })} />
            </label>
            <div className="flex gap-2">
              <button onClick={() => setForm(null)} className="flex-1 py-2 border border-[var(--haip-border)] rounded-lg text-xs text-[var(--haip-fg-muted)] hover:bg-[var(--haip-surface)]">Cancel</button>
              <button onClick={() => save.mutate()} disabled={!(Number(form.amount) > 0) || save.isPending}
                className="flex-1 py-2 bg-primary hover:bg-primary disabled:opacity-40 text-white font-semibold rounded-lg text-xs">
                {save.isPending ? "Saving..." : "Save deposit"}
              </button>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
