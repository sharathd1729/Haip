"use client";
// Lead page: what the lead autopilot did ("Moved to Lost by autopilot — reason, evidence, Undo"), a move it held
// back, and the pin that stops automation for this lead. Backend: LeadDetailSchema.autopilot
// (lead_autopilot_view.lead_block), POST /leads/{id}/autopilot/undo and /pin. An open suggestion is NOT shown
// here: it arrives as the "Suggested next step" card with Apply (recommended_actions).
import { useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { timeAgo } from "@/lib/utils";
import { Bot, Lock, Loader2, RotateCcw } from "@/lib/icons";
import { StatusPill } from "@/components/ui/page";
import { useToast } from "@/components/ui/toast";
import { autopilotHeadline, evidenceLabel, ruleLabel, type AutopilotBlock, type AutopilotEvent } from "@/lib/actionable";

function errorText(e: unknown): string {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === "string" ? detail : "Check your connection and try again.";
}

function EventBody({ e }: { e: AutopilotEvent }) {
  return (
    <>
      <p className="mt-1 text-[12px] text-[var(--haip-fg)]">
        {e.reason}
        {e.lost_reason_label ? <span className="text-[var(--haip-fg-muted)]"> · Reason: {e.lost_reason_label}</span> : null}
      </p>
      <p className="mt-0.5 text-[11px] text-[var(--haip-fg-subtle)]">
        {ruleLabel(e.rule)}
        {e.source === "ai" && e.confidence != null ? ` · AI confidence ${Math.round(e.confidence * 100)}%` : ""}
        {e.created_at ? ` · ${timeAgo(e.created_at)}` : ""}
      </p>
      {e.evidence.length > 0 && (
        <ul className="mt-1.5 space-y-1">
          {e.evidence.slice(0, 3).map((ev, i) => (
            <li key={`${ev.id}-${i}`} className="text-[12px] text-[var(--haip-fg-muted)]">
              <span className="font-medium text-[var(--haip-fg)]">{evidenceLabel(ev)}:</span>{" "}
              {ev.quote ? <span className="italic">&ldquo;{ev.quote}&rdquo;</span> : "on file"}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

export function AutopilotPanel({ inquiryId, autopilot, canEdit }: { inquiryId: string; autopilot?: AutopilotBlock | null; canEdit: boolean }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const refresh = (fresh: AutopilotBlock) => {
    qc.setQueryData(["lead", inquiryId], (old: Record<string, unknown> | undefined) => (old ? { ...old, autopilot: fresh } : old));
    qc.invalidateQueries({ queryKey: ["lead", inquiryId] });
    qc.invalidateQueries({ queryKey: ["leads"] });
  };
  const undo = useMutation({
    mutationFn: (eventId: string) => api.post(`/leads/${inquiryId}/autopilot/undo`, { event_id: eventId }).then(r => r.data),
    onSuccess: (fresh: AutopilotBlock) => { refresh(fresh); toast({ variant: "success", title: "Move undone", description: "The lead is back where it was." }); },
    onError: (e: unknown) => toast({ variant: "error", title: "Couldn't undo", description: errorText(e) }),
  });
  const pin = useMutation({
    mutationFn: (pinned: boolean) => api.post(`/leads/${inquiryId}/autopilot/pin`, { pinned }).then(r => r.data),
    onSuccess: (fresh: AutopilotBlock) => {
      refresh(fresh);
      toast({ variant: "success", title: fresh.pinned ? "Lead pinned" : "Autopilot back on", description: fresh.pinned ? "Autopilot will leave this lead alone." : "Autopilot can update this lead again." });
    },
    onError: (e: unknown) => toast({ variant: "error", title: "Couldn't change the pin", description: errorText(e) }),
  });

  if (!autopilot || autopilot.mode === "off") return null;
  const move = autopilot.last_move;
  const held = autopilot.suggestion?.status === "blocked" ? autopilot.suggestion : null;
  if (!move && !held && !canEdit) return null;

  return (
    <div className="haip-card p-3.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="flex items-center gap-1.5 text-[12px] font-semibold text-[var(--haip-fg)]">
          <Bot size={14} className="text-primary" /> Lead autopilot
          <StatusPill tone={autopilot.pinned ? "warning" : autopilot.mode === "autopilot" ? "brand" : "neutral"}>
            {autopilot.pinned ? "Pinned" : autopilot.mode === "autopilot" ? "On" : "Suggest only"}
          </StatusPill>
        </p>
        {canEdit && (
          <button type="button" onClick={() => pin.mutate(!autopilot.pinned)} disabled={pin.isPending}
            className="inline-flex min-h-[44px] items-center gap-1.5 rounded-full border border-[var(--haip-border)] px-3 text-[12px] font-medium text-[var(--haip-fg-muted)] hover:bg-[var(--haip-surface)] disabled:opacity-60 sm:min-h-[32px]">
            {pin.isPending ? <Loader2 size={12} className="animate-spin" /> : <Lock size={12} />}
            {autopilot.pinned ? "Unpin" : "Pin (stop automation)"}
          </button>
        )}
      </div>

      {move && (
        <div className="mt-2.5 border-t border-[var(--haip-border)] pt-2.5">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <p className="text-[13px] font-semibold text-[var(--haip-fg)]">{autopilotHeadline(move)}</p>
            {canEdit && move.can_undo && (
              <button type="button" onClick={() => undo.mutate(move.id)} disabled={undo.isPending}
                className="inline-flex min-h-[44px] items-center gap-1.5 rounded-full bg-primary px-3.5 text-[12px] font-semibold text-primary-foreground disabled:opacity-60 sm:min-h-[32px]">
                {undo.isPending ? <Loader2 size={12} className="animate-spin" /> : <RotateCcw size={12} />} Undo
              </button>
            )}
          </div>
          <EventBody e={move} />
        </div>
      )}

      {held && (
        <div className="mt-2.5 border-t border-[var(--haip-border)] pt-2.5">
          <p className="text-[13px] font-semibold text-[var(--haip-fg)]">{autopilotHeadline(held)}</p>
          {held.blocked_reason && <p className="mt-0.5 text-[12px] text-[var(--haip-status-warning-fg)]">Not moved: {held.blocked_reason}.</p>}
          <EventBody e={held} />
        </div>
      )}

      {!move && !held && (
        <p className="mt-2 text-[12px] text-[var(--haip-fg-subtle)]">
          {autopilot.pinned ? "Pinned: the autopilot will not move or suggest anything for this lead."
            : "Nothing changed automatically on this lead yet."}
        </p>
      )}
    </div>
  );
}
