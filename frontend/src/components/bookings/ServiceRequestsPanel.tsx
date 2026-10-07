"use client";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Trash2 } from "@/lib/icons";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";
import { errorMessage, fmtDate, type BookingDetail } from "@/lib/bookings";

const input = "w-full text-sm border border-gray-200 rounded-lg px-2.5 py-1.5 focus:outline-none focus:ring-2 focus:ring-teal-500";
const QUICK = ["Extra bed", "Late check-out", "Early check-in", "Airport cab"];

/** Things the team must do for this stay. Each one also lands on the assignee's My Day. */
export function ServiceRequestsPanel({ booking, onChange }: { booking: BookingDetail; onChange: (b: BookingDetail) => void }) {
  const { toast } = useToast();
  const base = `/bookings/${booking.id}/service-requests`;
  const [title, setTitle] = useState("");
  const [assignee, setAssignee] = useState("");
  const [due, setDue] = useState("");

  const run = useMutation({
    mutationFn: (req: () => Promise<{ data: BookingDetail }>) => req(),
    onSuccess: res => onChange(res.data),
    onError: e => toast({ variant: "error", title: errorMessage(e, "Could not update the request") }),
  });

  const add = (text: string) => {
    if (!text.trim()) return;
    run.mutate(() => api.post(base, { title: text.trim(), assigned_to: assignee || undefined, due_date: due || undefined }), {
      onSuccess: res => { onChange(res.data); setTitle(""); setDue(""); },
    });
  };

  return (
    <section className="haip-card">
      <div className="haip-card-head"><h2 className="haip-card-title">Service requests</h2></div>
      <div className="p-4 space-y-3">
        {booking.service_requests.length === 0 && <p className="text-sm text-gray-400">No requests for this stay.</p>}
        {booking.service_requests.map(r => (
          <div key={r.id} className="flex items-start gap-2.5 text-sm">
            <input
              type="checkbox" checked={r.status === "done"} aria-label={`Mark ${r.title} ${r.status === "done" ? "open" : "done"}`}
              onChange={() => run.mutate(() => api.patch(`${base}/${r.id}`, { status: r.status === "done" ? "open" : "done" }))}
              className="mt-1 h-4 w-4 rounded border-gray-300 text-teal-600 focus:ring-teal-500"
            />
            <div className="min-w-0 flex-1">
              <p className={cn("font-medium", r.status === "done" ? "text-gray-400 line-through" : "text-gray-900")}>{r.title}</p>
              <p className="text-xs text-gray-400">
                {r.assignee_name ?? "Unassigned"}{r.due_date ? ` · due ${fmtDate(r.due_date, false)}` : ""}
              </p>
            </div>
            <button aria-label={`Remove ${r.title}`} onClick={() => run.mutate(() => api.delete(`${base}/${r.id}`))}
              className="w-7 h-7 rounded-lg flex items-center justify-center text-gray-300 hover:text-red-500 hover:bg-red-50"><Trash2 size={13} /></button>
          </div>
        ))}

        <div className="pt-2 border-t border-gray-100 space-y-2">
          <div className="flex flex-wrap gap-1.5">
            {QUICK.map(q => (
              <button key={q} onClick={() => setTitle(q)} className="text-[11px] border border-gray-200 rounded-full px-2.5 py-1 text-gray-600 hover:bg-gray-50">{q}</button>
            ))}
          </div>
          <input className={input} placeholder="What needs to be done?" aria-label="Request" value={title}
            onChange={e => setTitle(e.target.value)} onKeyDown={e => { if (e.key === "Enter") add(title); }} />
          <div className="grid grid-cols-[1fr_8.5rem_auto] gap-2">
            <select className={input} aria-label="Assign to" value={assignee} onChange={e => setAssignee(e.target.value)}>
              <option value="">Unassigned</option>
              {booking.assignees.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
            <input className={input} type="date" aria-label="Due date" value={due} onChange={e => setDue(e.target.value)} />
            <button onClick={() => add(title)} disabled={!title.trim() || run.isPending}
              className="text-xs font-semibold bg-gray-900 text-white px-3 py-2 rounded-lg hover:bg-gray-700 disabled:opacity-40">Add</button>
          </div>
        </div>
      </div>
    </section>
  );
}
