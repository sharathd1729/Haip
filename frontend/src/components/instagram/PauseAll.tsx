"use client";
// "Pause all automations" for a set time (GET/PUT /instagram/automations/pause, audited). While paused nothing is sent;
// the banner says until when and resumes in one tap.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";

const OPTIONS: [number, string][] = [[1, "1 hour"], [4, "4 hours"], [24, "24 hours"], [72, "3 days"], [168, "7 days"]];

export function PauseAll() {
  const qc = useQueryClient();
  const [err, setErr] = useState("");
  const q = useQuery<{ paused_until: string | null }>({
    queryKey: ["ig-automations-pause"],
    queryFn: () => api.get("/instagram/automations/pause").then(r => r.data),
  });
  const set = useMutation({
    mutationFn: (hours: number | null) => api.put("/instagram/automations/pause", { hours }).then(r => r.data),
    onSuccess: data => { setErr(""); qc.setQueryData(["ig-automations-pause"], data); },
    onError: () => setErr("Couldn't change it. Try again."),
  });
  const until = q.data?.paused_until ? new Date(q.data.paused_until) : null;

  if (until) {
    return (
      <div role="status" className="flex flex-wrap items-center gap-2 rounded-[12px] border border-[var(--haip-status-warning-border)] bg-[var(--haip-status-warning-bg)] px-3 py-2">
        <p className="min-w-0 flex-1 text-[14px] font-medium">
          All Instagram automations are paused until {until.toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })}.
        </p>
        <button type="button" onClick={() => set.mutate(null)} disabled={set.isPending}
          className="min-h-11 rounded-full bg-primary px-4 text-[14px] font-semibold text-primary-foreground disabled:opacity-60">Resume now</button>
        {err && <p role="alert" className="w-full text-[13px] text-[var(--haip-status-danger-fg)]">{err}</p>}
      </div>
    );
  }
  return (
    <label className="inline-flex items-center gap-2 text-[14px]">
      <span className="sr-only">Pause all automations</span>
      <select value="" disabled={set.isPending || q.isLoading} onChange={e => { if (e.target.value) set.mutate(Number(e.target.value)); }}
        className="min-h-11 rounded-full border border-[var(--haip-border)] bg-[var(--haip-card)] px-4 text-[14.5px] font-medium">
        <option value="">Pause all…</option>
        {OPTIONS.map(([h, l]) => <option key={h} value={h}>Pause for {l}</option>)}
      </select>
      {err && <span role="alert" className="text-[13px] text-[var(--haip-status-danger-fg)]">{err}</span>}
    </label>
  );
}
