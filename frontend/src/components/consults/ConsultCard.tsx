"use client";
// "Ask a manager": a question the AI held back for a person (GET /consults). Shows what the guest asked, the AI's proposed answer,
// why it asked (reasons + sources) and Approve / Edit & send / Take over. The server sends the answer through the normal send path
// (or raises a "Reply needed" task when the 24 h window is closed) and answers 409 when someone already dealt with it.
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "@/lib/icons";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Card, CardBody, CardHeader, StatusPill } from "@/components/ui/kit";
import { useToast } from "@/components/ui/toast";
import { BTN, BTN_PRIMARY, INPUT } from "@/components/quotes/ui";

export type Consult = {
  id: string; conversation_id: string; guest_id: string | null; guest_name: string; inquiry_id: string | null; channel: string | null;
  status: "open" | "answered" | "taken_over" | "expired"; level: "agent" | "manager" | "owner";
  reasons: { code: string; label: string }[]; question: string; proposed_answer: string | null;
  options: { id: string; text: string }[];
  evidence: { flags?: string[]; sources?: { kind?: string; key?: string; version?: number }[]; holding_not_sent?: string };
  sla_due_at: string | null; overdue: boolean; created_at: string; holding_sent: boolean; window_open: boolean | null;
  assigned_name: string | null; answered_name: string | null; answer_mode: string | null; delivery: string | null;
};

const LEVEL: Record<Consult["level"], string> = { agent: "For the lead's owner", manager: "For a manager", owner: "For the owner" };

function due(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit", timeZone: "Asia/Kolkata" });
}

function errorText(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: { message?: string } | string } } })?.response?.data?.detail;
  return typeof d === "string" ? d : d?.message ?? "Something went wrong. Try again.";
}

type Answer = { mode: "approve_proposed" | "edited" | "option"; text?: string; option_id?: string; save_to_kb?: boolean };

export function ConsultCard({ consult: c, compact = false }: { consult: Consult; compact?: boolean }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(c.proposed_answer ?? "");
  const [saveKb, setSaveKb] = useState(false);
  const done = () => {
    qc.invalidateQueries({ queryKey: ["consults"] });
    qc.invalidateQueries({ queryKey: ["work-queue"] });
  };
  const answer = useMutation({
    mutationFn: (body: Answer) => api.post(`/consults/${c.id}/answer`, body).then(r => r.data),
    onSuccess: (d: { delivery: string }) => {
      toast({ variant: "success", title: d.delivery === "window_closed_task" ? "Saved: the 24-hour window is closed, a reply task was added" : "Sent to the guest" });
      done();
    },
    onError: e => { toast({ variant: "error", title: "Not sent", description: errorText(e) }); done(); },
  });
  const takeOver = useMutation({
    mutationFn: () => api.post(`/consults/${c.id}/take-over`).then(r => r.data),
    onSuccess: () => { toast({ variant: "success", title: "It's yours: reply in the Inbox" }); done(); },
    onError: e => { toast({ variant: "error", title: "Couldn't take over", description: errorText(e) }); done(); },
  });
  const busy = answer.isPending || takeOver.isPending;
  const sources = (c.evidence.sources ?? []).map(s => [s.kind, s.key].filter(Boolean).join(": ")).filter(Boolean);

  return (
    <Card aria-label={`Question from ${c.guest_name}`}>
      <CardHeader
        title={`${c.guest_name} asked`}
        description={`${LEVEL[c.level]} · answer by ${due(c.sla_due_at)}${c.holding_sent ? " · the guest was told we're checking" : ""}`}
        actions={<StatusPill tone={c.overdue ? "danger" : "warning"}>{c.overdue ? "Overdue" : "Waiting for you"}</StatusPill>}
      />
      <CardBody className="space-y-3">
        <p className="whitespace-pre-line break-words rounded-lg bg-[var(--haip-surface)] p-3 text-[14px] text-[var(--haip-fg)]">“{c.question}”</p>
        <ul className="flex flex-wrap gap-1.5" aria-label="Why the AI asked">
          {c.reasons.map(r => <li key={r.code}><StatusPill tone="neutral">{r.label}</StatusPill></li>)}
        </ul>
        {!compact && sources.length > 0 && (
          <p className="break-words text-[12px] text-[var(--haip-fg-subtle)]">Sources the AI read: {sources.join(", ")}</p>
        )}
        {editing ? (
          <div className="space-y-2">
            <label htmlFor={`consult-${c.id}`} className="block text-xs font-semibold text-[var(--haip-fg-2)]">Your answer to the guest</label>
            <textarea id={`consult-${c.id}`} value={text} onChange={e => setText(e.target.value)} maxLength={2000} className={cn(INPUT, "h-28 py-2")} />
          </div>
        ) : c.proposed_answer ? (
          <div className="min-w-0 rounded-lg border border-[var(--haip-border)] p-3">
            <p className="text-[12px] font-semibold text-[var(--haip-fg-subtle)]">The AI would say (not sent)</p>
            <p className="mt-0.5 whitespace-pre-line break-words text-[14px] text-[var(--haip-fg)]">{c.proposed_answer}</p>
          </div>
        ) : (
          <p className="text-[13px] text-[var(--haip-fg-subtle)]">The AI has no answer to suggest. Write one or take over.</p>
        )}
        {c.options.length > 0 && !editing && (
          <div className="flex flex-wrap gap-2">
            {c.options.map(o => (
              <button key={o.id} type="button" className={BTN} disabled={busy} onClick={() => answer.mutate({ mode: "option", option_id: o.id })}>{o.text}</button>
            ))}
          </div>
        )}
        {c.window_open === false && (
          <p className="text-[13px] text-[var(--haip-status-warning-fg)]">The guest's 24-hour window is closed: your answer is saved and a reply task is added.</p>
        )}
        <label className="flex min-h-11 items-center gap-2 text-[13px] text-[var(--haip-fg-2)]">
          <input type="checkbox" checked={saveKb} onChange={e => setSaveKb(e.target.checked)} className="accent-primary" />
          Save the answer to the knowledge base (the owner approves it first)
        </label>
        <div className="flex flex-wrap gap-2">
          {editing ? (
            <>
              <button type="button" className={BTN_PRIMARY} disabled={busy || !text.trim()} onClick={() => answer.mutate({ mode: "edited", text, save_to_kb: saveKb })}>
                {answer.isPending ? <Loader2 size={14} className="animate-spin" /> : "Send my answer"}
              </button>
              <button type="button" className={BTN} disabled={busy} onClick={() => setEditing(false)}>Cancel</button>
            </>
          ) : (
            <>
              {c.proposed_answer && (
                <button type="button" className={BTN_PRIMARY} disabled={busy} onClick={() => answer.mutate({ mode: "approve_proposed", save_to_kb: saveKb })}>
                  {answer.isPending ? <Loader2 size={14} className="animate-spin" /> : "Approve & send"}
                </button>
              )}
              <button type="button" className={BTN} disabled={busy} onClick={() => setEditing(true)}>Edit & send</button>
              <button type="button" className={BTN} disabled={busy} onClick={() => takeOver.mutate()}>Take over</button>
            </>
          )}
          {compact && <a className={BTN} href={`/dashboard/inbox?conversation=${c.conversation_id}&consult=${c.id}`}>Open chat</a>}
        </div>
      </CardBody>
    </Card>
  );
}
