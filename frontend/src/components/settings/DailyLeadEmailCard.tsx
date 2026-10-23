"use client";
// Settings > Lead rules: the daily lead report email (lead_report_email). Owners + managers get yesterday's report at the
// chosen time (IST); reservations + concierge get "Update your leads before HH:MM" 30 minutes earlier. Off by default.
// Backend: GET/PUT /reports/daily-lead-email/settings (owner/manager, audited).
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { Loader2 } from "@/lib/icons";
import { useToast } from "@/components/ui/toast";
import { Card, CardBody, CardHeader } from "@/components/ui/kit";

interface Cfg { enabled: boolean; hour: number; minute: number; reminder: boolean; last_sent?: string | null }

const pad = (n: number) => String(n).padStart(2, "0");

export function DailyLeadEmailCard() {
  const qc = useQueryClient();
  const { toast } = useToast();
  const q = useQuery<Cfg>({ queryKey: ["daily-lead-email"], queryFn: () => api.get("/reports/daily-lead-email/settings").then(r => r.data) });
  const [cfg, setCfg] = useState<Cfg | null>(null);
  useEffect(() => { if (q.data) setCfg(q.data); }, [q.data]);
  const save = useMutation({
    mutationFn: () => api.put("/reports/daily-lead-email/settings", { enabled: cfg!.enabled, hour: cfg!.hour, minute: cfg!.minute, reminder: cfg!.reminder }).then(r => r.data as Cfg),
    onSuccess: d => { qc.setQueryData(["daily-lead-email"], d); toast({ variant: "success", title: "Saved · logged" }); },
    onError: () => toast({ variant: "error", title: "Not saved", description: "Try again." }),
  });
  return (
    <Card>
      <CardHeader title="Daily lead report email" description="Yesterday's lead report to owners and managers, every morning (IST)." />
      <CardBody className="grid gap-3">
        {q.isPending ? (
          <p className="flex items-center gap-2 text-sm text-[var(--haip-fg-muted)]"><Loader2 size={14} className="animate-spin" aria-hidden /> Loading…</p>
        ) : q.isError || !cfg ? (
          <p className="text-sm text-[var(--haip-fg-muted)]">Couldn&apos;t load this. <button type="button" className="font-semibold text-primary" onClick={() => q.refetch()}>Try again</button></p>
        ) : (
          <>
            <label className="flex min-h-11 items-center gap-2.5 text-[14.5px] font-semibold text-[var(--haip-fg)]">
              <input type="checkbox" className="size-5 accent-[var(--primary)]" checked={cfg.enabled} onChange={e => setCfg({ ...cfg, enabled: e.target.checked })} />
              Send the daily lead report
            </label>
            <label className="grid gap-1">
              <span className="text-[13px] font-semibold text-[var(--haip-fg-2)]">Send at (IST)</span>
              <input type="time" step={300} disabled={!cfg.enabled} value={`${pad(cfg.hour)}:${pad(cfg.minute)}`}
                onChange={e => { const [h, m] = e.target.value.split(":").map(Number); if (Number.isFinite(h) && Number.isFinite(m)) setCfg({ ...cfg, hour: h, minute: m }); }}
                className="min-h-11 w-40 rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-[16px] text-[var(--haip-fg)] sm:text-sm" />
            </label>
            <label className="flex min-h-11 items-start gap-2.5 text-[14px] text-[var(--haip-fg)]">
              <input type="checkbox" className="mt-0.5 size-5 accent-[var(--primary)]" disabled={!cfg.enabled} checked={cfg.reminder}
                onChange={e => setCfg({ ...cfg, reminder: e.target.checked })} />
              <span><span className="block font-semibold">Remind the team 30 minutes before</span>
                <span className="block text-[12.5px] text-[var(--haip-fg-subtle)]">Reservations and concierge get “Update your leads before {pad(cfg.hour)}:{pad(cfg.minute)}”.</span></span>
            </label>
            {cfg.last_sent && <p className="text-[12.5px] text-[var(--haip-fg-subtle)]">Last sent {cfg.last_sent}.</p>}
            <button type="button" disabled={save.isPending} onClick={() => save.mutate()}
              className="inline-flex min-h-11 items-center justify-center justify-self-start gap-1.5 rounded-xl bg-primary px-4 text-[14px] font-semibold text-primary-foreground disabled:opacity-60">
              {save.isPending && <Loader2 size={14} className="animate-spin" aria-hidden />} Save
            </button>
          </>
        )}
      </CardBody>
    </Card>
  );
}
