"use client";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Plus, Trash2 } from "@/lib/icons";
import api from "@/lib/api";
import { cn, formatINR } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";
import { errorMessage, fmtDate, type BookingDetail } from "@/lib/bookings";

const input = "w-full text-sm border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-teal-500";

const STATUS: Record<string, { label: string; cls: string }> = {
  paid:    { label: "Paid",     cls: "bg-emerald-50 text-emerald-700 border-emerald-100" },
  partial: { label: "Part paid", cls: "bg-amber-50 text-amber-800 border-amber-100" },
  due:     { label: "Upcoming", cls: "bg-gray-100 text-gray-600 border-gray-200" },
  overdue: { label: "Overdue",  cls: "bg-red-50 text-red-700 border-red-100" },
};

interface Row { label: string; amount: string; due_date: string }

function addDays(iso: string, n: number): string {
  const d = new Date(`${iso}T00:00:00`);
  d.setDate(d.getDate() + n);
  const pad = (x: number) => String(x).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** Instalment plan for the booking. Which instalments are paid is worked out from the recorded payments. */
export function SchedulePanel({ booking, onChange }: { booking: BookingDetail; onChange: (b: BookingDetail) => void }) {
  const { toast } = useToast();
  const total = booking.financials.total;
  const [rows, setRows] = useState<Row[] | null>(null);

  const save = useMutation({
    mutationFn: (items: Row[]) => api.put(`/bookings/${booking.id}/schedule`, {
      items: items.map(r => ({ label: r.label.trim(), amount: Number(r.amount), due_date: r.due_date })),
    }),
    onSuccess: res => { onChange(res.data); setRows(null); toast({ variant: "success", title: "Payment schedule saved" }); },
    onError: e => toast({ variant: "error", title: errorMessage(e, "Could not save the schedule") }),
  });

  const today = new Date().toISOString().slice(0, 10);
  const startEdit = () => setRows(booking.schedule.map(s => ({ label: s.label, amount: String(s.amount), due_date: s.due_date })));
  const preset = (advancePct: number) => {
    const adv = Math.round((total * advancePct) / 100);
    const balanceDue = addDays(booking.check_in, -7);
    setRows([
      { label: "Advance", amount: String(adv), due_date: today },
      { label: "Balance", amount: String(Math.max(total - adv, 0)), due_date: balanceDue < today ? booking.check_in : balanceDue },
    ]);
  };

  const planned = rows ? rows.reduce((n, r) => n + (Number(r.amount) || 0), 0) : 0;
  const valid = !!rows && rows.every(r => r.label.trim() && Number(r.amount) > 0 && r.due_date) && planned <= total + 0.005;

  return (
    <section className="haip-card">
      <div className="haip-card-head">
        <h2 className="haip-card-title">Payment schedule</h2>
        {!rows && <button onClick={startEdit} className="ml-auto text-xs font-semibold text-teal-700 hover:underline">{booking.schedule.length ? "Edit" : "Set up"}</button>}
      </div>
      <div className="p-4 space-y-3">
        {!rows && booking.schedule.length === 0 && (
          <div className="space-y-2">
            <p className="text-sm text-gray-400">No instalments planned. Add due dates so overdue balances show in the bookings list.</p>
            {total > 0 && (
              <div className="flex flex-wrap gap-2">
                <button onClick={() => preset(30)} className="text-xs font-semibold border border-gray-200 px-3 py-1.5 rounded-lg hover:bg-gray-50">30% now, rest 7 days before</button>
                <button onClick={() => preset(50)} className="text-xs font-semibold border border-gray-200 px-3 py-1.5 rounded-lg hover:bg-gray-50">50 / 50</button>
              </div>
            )}
          </div>
        )}

        {!rows && booking.schedule.map(s => (
          <div key={s.id} className="flex items-center gap-2 text-sm">
            <div className="min-w-0 flex-1">
              <p className="font-medium text-gray-900">{s.label}</p>
              <p className="text-xs text-gray-400">Due {fmtDate(s.due_date)}</p>
            </div>
            <span className="tabular-nums font-medium">{formatINR(s.amount)}</span>
            <span className={cn("inline-flex rounded-full border px-2 py-0.5 text-[11px] font-semibold", STATUS[s.status].cls)}>{STATUS[s.status].label}</span>
          </div>
        ))}

        {rows && (
          <>
            {rows.map((r, i) => (
              <div key={i} className="grid grid-cols-[1fr_6rem_8rem_auto] gap-2 items-center">
                <input className={input} placeholder="Label" aria-label="Label" value={r.label} onChange={e => setRows(rs => rs && rs.map((x, j) => j === i ? { ...x, label: e.target.value } : x))} />
                <input className={input} placeholder="₹" aria-label="Amount" inputMode="decimal" value={r.amount}
                  onChange={e => setRows(rs => rs && rs.map((x, j) => j === i ? { ...x, amount: e.target.value.replace(/[^0-9.]/g, "") } : x))} />
                <input className={input} type="date" aria-label="Due date" value={r.due_date} onChange={e => setRows(rs => rs && rs.map((x, j) => j === i ? { ...x, due_date: e.target.value } : x))} />
                <button aria-label="Remove instalment" onClick={() => setRows(rs => rs && rs.filter((_, j) => j !== i))}
                  className="w-7 h-7 rounded-lg flex items-center justify-center text-gray-400 hover:text-red-500 hover:bg-red-50"><Trash2 size={13} /></button>
              </div>
            ))}
            <div className="flex items-center justify-between text-xs">
              <button onClick={() => setRows(rs => rs && [...rs, { label: "", amount: "", due_date: today }])} className="flex items-center gap-1 font-semibold text-teal-700"><Plus size={12} /> Add instalment</button>
              <span className={cn("tabular-nums", planned > total + 0.005 ? "text-red-600" : "text-gray-500")}>
                {formatINR(planned)} of {formatINR(total)} planned
              </span>
            </div>
            <div className="flex gap-2">
              <button onClick={() => setRows(null)} className="flex-1 py-2 border border-gray-200 rounded-lg text-xs text-gray-600 hover:bg-gray-50">Cancel</button>
              <button onClick={() => save.mutate(rows)} disabled={(!valid && rows.length > 0) || save.isPending}
                className="flex-1 py-2 bg-teal-500 hover:bg-teal-600 disabled:opacity-40 text-white font-semibold rounded-lg text-xs">
                {save.isPending ? "Saving..." : "Save schedule"}
              </button>
            </div>
          </>
        )}
      </div>
    </section>
  );
}
