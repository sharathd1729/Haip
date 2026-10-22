"use client";
// "Log a call": a call made from the agent's own phone, which the IVR never sees. POST /leads/{id}/log-call writes it as a
// normal call on the lead (outbound, by the person logging it). A connected call closes the guest's call-back reminders and
// counts as returning a missed call, so the next step moves on (lib/leadNextStep.ts reads the refreshed feed).
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Check, Loader2 } from "@/lib/icons";
import { Drawer } from "@/components/ui/kit";
import { useToast } from "@/components/ui/toast";

export type LogOutcome = "connected" | "no_answer" | "voicemail";

const OUTCOMES: { key: LogOutcome; label: string; hint: string }[] = [
  { key: "connected", label: "We spoke", hint: "Counts as calling them back" },
  { key: "no_answer", label: "No answer", hint: "Logged as an attempt" },
  { key: "voicemail", label: "Voicemail / switched off", hint: "Logged as an attempt" },
];

const opt = "flex min-h-[52px] w-full items-center justify-between gap-2 rounded-xl border bg-[var(--haip-card)] px-3 py-2 text-left text-[14.5px] text-[var(--haip-fg)]";
const input = "min-h-11 w-full rounded-lg border border-[var(--haip-border-strong)] bg-[var(--haip-card)] px-3 text-[16px] text-[var(--haip-fg)]";

function errText(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof d === "string" ? d : "Please try again.";
}

export function LogCallSheet({ open, onClose, inquiryId, name }: { open: boolean; onClose: () => void; inquiryId: string; name: string }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [outcome, setOutcome] = useState<LogOutcome>("connected");
  const [minutes, setMinutes] = useState("");
  const [note, setNote] = useState("");
  const reset = () => { setOutcome("connected"); setMinutes(""); setNote(""); };
  const save = useMutation({
    mutationFn: () => api.post(`/leads/${inquiryId}/log-call`, {
      outcome, note: note.trim() || undefined,
      duration_minutes: outcome === "connected" && minutes.trim() ? Math.max(0, Math.min(600, Number(minutes) || 0)) : undefined,
    }).then(r => r.data as { callbacks_closed: number }),
    onSuccess: (d) => {
      toast({ variant: "success", title: outcome === "connected" ? "Call logged" : "Attempt logged",
        description: d.callbacks_closed ? `${d.callbacks_closed} call-back reminder${d.callbacks_closed === 1 ? "" : "s"} closed.` : "It shows in the conversation." });
      for (const key of [["lead-feed", inquiryId], ["lead", inquiryId], ["work-queue"], ["calls"]]) qc.invalidateQueries({ queryKey: key });
      reset(); onClose();
    },
    onError: (e) => toast({ variant: "error", title: "Not logged", description: errText(e) }),
  });
  return (
    <Drawer open={open} onOpenChange={o => { if (!o) onClose(); }} title="Log a call"
      description={`Called ${name} from your own phone? Log it here so the team sees it and the reminders stop.`}>
      <div className="grid gap-3" data-testid="log-call-sheet">
        <div className="grid gap-1.5" role="radiogroup" aria-label="How did it go">
          {OUTCOMES.map(o => (
            <button key={o.key} type="button" role="radio" aria-checked={outcome === o.key} onClick={() => setOutcome(o.key)}
              className={cn(opt, outcome === o.key ? "border-primary ring-1 ring-primary" : "border-[var(--haip-border)]")}>
              <span>{o.label}<span className="block text-[12.5px] text-[var(--haip-fg-subtle)]">{o.hint}</span></span>
              {outcome === o.key && <Check size={16} className="text-primary" aria-hidden />}
            </button>
          ))}
        </div>
        {outcome === "connected" && (
          <label className="grid gap-1 text-[12.5px] font-semibold text-[var(--haip-fg-2)]">Minutes (optional)
            <input className={input} inputMode="numeric" value={minutes} onChange={e => setMinutes(e.target.value.replace(/\D/g, "").slice(0, 3))} placeholder="e.g. 5" />
          </label>
        )}
        <label className="grid gap-1 text-[12.5px] font-semibold text-[var(--haip-fg-2)]">Note (optional)
          <input className={input} value={note} maxLength={500} onChange={e => setNote(e.target.value)} placeholder="What did you agree?" />
        </label>
        <button type="button" disabled={save.isPending} onClick={() => save.mutate()}
          className="inline-flex min-h-11 items-center justify-center gap-1.5 rounded-xl bg-primary px-4 text-[14px] font-semibold text-primary-foreground disabled:opacity-60">
          {save.isPending && <Loader2 size={14} className="animate-spin" aria-hidden />} Log the call
        </button>
      </div>
    </Drawer>
  );
}
