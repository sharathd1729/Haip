"use client";
// The lead page's small sheets: move stage, mark lost (with a reason), owner, add a task, and the phone "More" menu.
// Stage moves go through PATCH /inquiries/{id} {stage_id}, the audited state-machine path (update_stage_by_id).
import { useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Check, Flag, Loader2 } from "@/lib/icons";
import { Drawer } from "@/components/ui/kit";
import { useToast } from "@/components/ui/toast";
import { LOST_REASON_LABEL } from "@/lib/leadNextStep";
import type { LeadActionKey, PipelineStage } from "./types";

export type SheetKey = "stage" | "lost" | "owner" | "task" | "more" | null;

function errText(e: unknown, fallback: string) {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof d === "string" ? d : fallback;
}

const opt = "flex min-h-[52px] w-full items-center justify-between gap-2 rounded-xl border bg-[var(--haip-card)] px-3 py-2 text-left text-[14.5px] text-[var(--haip-fg)]";
const input = "min-h-11 w-full rounded-lg border border-[var(--haip-border-strong)] bg-[var(--haip-card)] px-3 text-[16px] text-[var(--haip-fg)]";
const primaryBtn = "inline-flex min-h-11 items-center justify-center gap-1.5 rounded-xl bg-primary px-4 text-[14px] font-semibold text-primary-foreground disabled:opacity-60";

function useLeadPatch(inquiryId: string, done: () => void, okTitle: (body: Record<string, unknown>) => string) {
  const qc = useQueryClient();
  const { toast } = useToast();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) => api.patch(`/inquiries/${inquiryId}`, body).then(() => body),
    onSuccess: (body) => {
      toast({ variant: "success", title: okTitle(body) });
      qc.invalidateQueries({ queryKey: ["lead", inquiryId] });
      qc.invalidateQueries({ queryKey: ["lead-feed", inquiryId] });
      qc.invalidateQueries({ queryKey: ["leads"] });
      done();
    },
    onError: (e) => toast({ variant: "error", title: "Not changed", description: errText(e, "Please try again.") }),
  });
}

export function StageSheet({ open, onClose, inquiryId, stages, currentKey, canReverse, onLost }: {
  open: boolean; onClose: () => void; inquiryId: string; stages: PipelineStage[]; currentKey?: string | null; canReverse: boolean; onLost: () => void;
}) {
  const [backTo, setBackTo] = useState<PipelineStage | null>(null);
  const [reason, setReason] = useState("");
  const current = stages.find(s => s.key === currentKey);
  const patch = useLeadPatch(inquiryId, () => { setBackTo(null); setReason(""); onClose(); },
    () => `Stage changed${backTo ? ` to ${backTo.label}` : ""} · logged`);
  const terminal = !!current && (current.is_closed_lost || current.is_closed_won);
  const pick = (s: PipelineStage) => {
    if (s.key === currentKey) return onClose();
    if (s.is_closed_lost) return onLost();
    if (current && s.order < current.order && !s.is_closed_won) { setBackTo(s); return; }
    patch.mutate({ stage_id: s.id });
  };
  return (
    <Drawer open={open} onOpenChange={o => { if (!o) { setBackTo(null); onClose(); } }} title="Move stage"
      description={terminal ? `${current!.label} is a closed stage. Only an owner or manager can reopen a lost lead, from the Leads list.` : "Every move is logged on the lead."}>
      {backTo ? (
        <div className="grid gap-3">
          <p className="text-[14px] text-[var(--haip-fg-2)]">Moving back to <strong>{backTo.label}</strong> needs a reason{canReverse ? "" : " and an owner or manager"}.</p>
          <label className="grid gap-1 text-[12.5px] font-semibold text-[var(--haip-fg-2)]">Reason
            <input className={input} value={reason} onChange={e => setReason(e.target.value)} placeholder="e.g. dates changed, back to qualifying" />
          </label>
          <div className="flex gap-2">
            <button type="button" className={primaryBtn} disabled={!reason.trim() || patch.isPending}
              onClick={() => patch.mutate({ stage_id: backTo.id, reason: reason.trim() })}>
              {patch.isPending && <Loader2 size={14} className="animate-spin" aria-hidden />} Move back
            </button>
            <button type="button" onClick={() => setBackTo(null)} className="min-h-11 rounded-xl px-4 text-[14px] font-semibold text-[var(--haip-fg-2)]">Cancel</button>
          </div>
        </div>
      ) : (
        <div className="grid gap-2" role="radiogroup" aria-label="Stage">
          {[...stages].sort((a, b) => a.order - b.order).map(s => (
            <button key={s.id} type="button" role="radio" aria-checked={s.key === currentKey} disabled={terminal || patch.isPending}
              onClick={() => pick(s)} className={cn(opt, s.key === currentKey ? "border-primary ring-1 ring-primary" : "border-[var(--haip-border)]", "disabled:opacity-60")}>
              <span>{s.label}{s.category === "valid" && <span className="block text-[12.5px] text-[var(--haip-fg-subtle)]">Counts as a real lead</span>}</span>
              {s.key === currentKey && <Check size={16} className="text-primary" aria-hidden />}
            </button>
          ))}
        </div>
      )}
    </Drawer>
  );
}

export function LostSheet({ open, onClose, inquiryId, name, lostStage }: {
  open: boolean; onClose: () => void; inquiryId: string; name: string; lostStage?: PipelineStage;
}) {
  const [note, setNote] = useState("");
  const patch = useLeadPatch(inquiryId, () => { setNote(""); onClose(); }, () => "Marked lost · reminders stopped");
  return (
    <Drawer open={open} onOpenChange={o => { if (!o) onClose(); }} title="Mark as lost"
      description={`Why did ${name} not book? Reminders stop; if ${name} writes again it shows in My day.`}>
      {!lostStage ? <p className="text-[14px] text-[var(--haip-fg-muted)]">This workspace has no Lost stage. Add one in Leads → Pipeline settings.</p> : (
        <div className="grid gap-2">
          <label className="grid gap-1 text-[12.5px] font-semibold text-[var(--haip-fg-2)]">Note (optional)
            <input className={input} value={note} onChange={e => setNote(e.target.value)} placeholder="Anything the team should know" />
          </label>
          {Object.entries(LOST_REASON_LABEL).map(([k, label]) => (
            <button key={k} type="button" disabled={patch.isPending} className={cn(opt, "border-[var(--haip-border)] disabled:opacity-60")}
              onClick={() => patch.mutate({ stage_id: lostStage.id, lost_reason: k, ...(note.trim() ? { lost_note: note.trim() } : {}) })}>
              {label}
            </button>
          ))}
        </div>
      )}
    </Drawer>
  );
}

export function OwnerSheet({ open, onClose, inquiryId, ownerId }: { open: boolean; onClose: () => void; inquiryId: string; ownerId?: string | null }) {
  const { data: users = [], isPending, isError } = useQuery<{ id: string; name: string }[]>({
    queryKey: ["users-lite"], queryFn: () => api.get("/users/lite").then(r => r.data), enabled: open, staleTime: 60_000,
  });
  const patch = useLeadPatch(inquiryId, onClose, () => "Owner changed");
  return (
    <Drawer open={open} onOpenChange={o => { if (!o) onClose(); }} title="Lead owner" description="The owner gets this lead's reminders in My day.">
      {isPending ? <p className="text-[14px] text-[var(--haip-fg-subtle)]">Loading the team…</p>
        : isError ? <p className="text-[14px] text-[var(--haip-status-danger-fg)]">Couldn&apos;t load the team. Try again.</p>
          : (
            <div className="grid gap-2" role="radiogroup" aria-label="Owner">
              {users.map(u => (
                <button key={u.id} type="button" role="radio" aria-checked={u.id === ownerId} disabled={patch.isPending}
                  onClick={() => (u.id === ownerId ? onClose() : patch.mutate({ assigned_to: u.id }))}
                  className={cn(opt, u.id === ownerId ? "border-primary ring-1 ring-primary" : "border-[var(--haip-border)]")}>
                  {u.name}{u.id === ownerId && <Check size={16} className="text-primary" aria-hidden />}
                </button>
              ))}
            </div>
          )}
    </Drawer>
  );
}

const DUE = [
  { label: "In 2 hours", at: () => new Date(Date.now() + 2 * 3_600_000) },
  { label: "This evening, 6 pm", at: () => { const d = new Date(); d.setHours(18, 0, 0, 0); return d; } },
  { label: "Tomorrow, 10 am", at: () => { const d = new Date(); d.setDate(d.getDate() + 1); d.setHours(10, 0, 0, 0); return d; } },
  { label: "No due time", at: () => null },
];

export function TaskSheet({ open, onClose, inquiryId, guestId, meId, name }: {
  open: boolean; onClose: () => void; inquiryId: string; guestId: string; meId?: string | null; name: string;
}) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [title, setTitle] = useState("");
  const [due, setDue] = useState(0);
  const add = useMutation({
    mutationFn: () => api.post("/tasks", {
      title: title.trim(), inquiry_id: inquiryId, guest_id: guestId, assigned_to: meId || undefined,
      due_date: DUE[due].at()?.toISOString() ?? undefined,
    }),
    onSuccess: () => {
      toast({ variant: "success", title: "Task added", description: "It shows here and in My day." });
      qc.invalidateQueries({ queryKey: ["lead-feed", inquiryId] });
      setTitle(""); onClose();
    },
    onError: (e) => toast({ variant: "error", title: "Task not added", description: errText(e, "Please try again.") }),
  });
  return (
    <Drawer open={open} onOpenChange={o => { if (!o) onClose(); }} title="Add a task">
      <div className="grid gap-3">
        <label className="grid gap-1 text-[12.5px] font-semibold text-[var(--haip-fg-2)]">What
          <input className={input} value={title} onChange={e => setTitle(e.target.value)} placeholder={`e.g. Call ${name} to confirm the advance`} />
        </label>
        <div className="grid gap-1.5" role="radiogroup" aria-label="When">
          {DUE.map((d, i) => (
            <button key={d.label} type="button" role="radio" aria-checked={due === i} onClick={() => setDue(i)}
              className={cn(opt, "min-h-11", due === i ? "border-primary ring-1 ring-primary" : "border-[var(--haip-border)]")}>
              {d.label}{due === i && <Check size={16} className="text-primary" aria-hidden />}
            </button>
          ))}
        </div>
        <button type="button" className={primaryBtn} disabled={!title.trim() || add.isPending} onClick={() => add.mutate()}>
          {add.isPending && <Loader2 size={14} className="animate-spin" aria-hidden />} Add task
        </button>
      </div>
    </Drawer>
  );
}

export function MoreSheet({ open, onClose, items }: {
  open: boolean; onClose: () => void; items: { key: LeadActionKey | "reveal"; label: string; hint?: string; icon?: ReactNode; onClick: () => void }[];
}) {
  return (
    <Drawer open={open} onOpenChange={o => { if (!o) onClose(); }} title="More actions">
      <div className="grid gap-2">
        {items.map(it => (
          <button key={it.key} type="button" onClick={it.onClick} className={cn(opt, "border-[var(--haip-border)]")}>
            <span className="flex items-center gap-2">{it.icon ?? <Flag size={15} aria-hidden />}<span>{it.label}
              {it.hint && <span className="block text-[12.5px] text-[var(--haip-fg-subtle)]">{it.hint}</span>}</span></span>
          </button>
        ))}
      </div>
    </Drawer>
  );
}
