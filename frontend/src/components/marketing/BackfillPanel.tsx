"use client";
// Load older ad history from Meta, a month at a time, in the background. Shows progress while it runs.
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";
import { errorText, longDate, type AdsStatus } from "./ads";

const CHOICES = [{ v: 6, l: "6 months" }, { v: 12, l: "12 months" }, { v: 24, l: "24 months" }, { v: 36, l: "3 years" }];

const WHY: Record<string, string> = {
  rate_limited: "Meta asked us to slow down. Start again in a few minutes and it picks up the rest.",
  token_rejected: "Meta rejected the access token. Save a new token under Settings, Integrations, then start again.",
  error: "Something went wrong on our side. Start again; nothing already loaded is lost.",
  not_queued: "The background worker could not be reached. Try again in a minute.",
};

export function BackfillPanel({ status, canStart }: { status: AdsStatus; canStart: boolean }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [months, setMonths] = useState(12);
  const b = status.backfill;
  const busy = b?.state === "queued" || b?.state === "running";
  const start = useMutation({
    mutationFn: () => api.post("/marketing/ads/backfill", { months }).then(r => r.data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["ads-status"] }); toast({ variant: "success", title: "Loading history", description: "This runs in the background. You can leave the page." }); },
    onError: e => toast({ variant: "error", title: "Could not start", description: errorText(e, "Try again.") }),
  });

  const total = b?.total ?? 0;
  const done = b?.done ?? 0;
  const failed = b?.failed?.length ?? 0;
  const loadedTo = status.earliest_data ? `Data goes back to ${longDate(status.earliest_data)}.` : "No history loaded yet.";

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-[var(--haip-border)] bg-[var(--haip-surface)] px-3 py-2.5 text-sm">
      <div className="min-w-0 flex-1">
        {busy ? (
          <>
            <p className="font-semibold text-[var(--haip-fg)]">Loading history… {done} of {total} months</p>
            <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-[var(--haip-border)]" role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={done}>
              <div className="h-full rounded-full bg-primary transition-[width] duration-500" style={{ width: `${total ? (done / total) * 100 : 5}%` }} />
            </div>
          </>
        ) : (
          <>
            <p className="font-semibold text-[var(--haip-fg)]">{b?.state === "stopped" ? "History load stopped" : b?.state === "done" ? "History loaded" : "Older history"}</p>
            <p className="text-xs text-[var(--haip-fg-subtle)]">
              {b?.state === "stopped" && b.stopped_because ? `${WHY[b.stopped_because] ?? "It stopped early."} ` : ""}
              {loadedTo}
              {failed > 0 ? ` ${failed} month${failed === 1 ? "" : "s"} could not be loaded.` : ""}
            </p>
          </>
        )}
      </div>
      {canStart && !busy && (
        <div className="flex items-center gap-2">
          <select value={months} onChange={e => setMonths(Number(e.target.value))} aria-label="How far back to load"
            className="h-9 rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-2.5 text-[12.5px] text-[var(--haip-fg)]">
            {CHOICES.map(c => <option key={c.v} value={c.v}>{c.l}</option>)}
          </select>
          <button type="button" onClick={() => start.mutate()} disabled={start.isPending}
            className={cn("h-9 rounded-lg px-3.5 text-[13px] font-semibold disabled:opacity-50", "bg-primary text-primary-foreground")}>
            {start.isPending ? "Starting…" : b?.state === "stopped" ? "Resume" : "Load history"}
          </button>
        </div>
      )}
    </div>
  );
}
