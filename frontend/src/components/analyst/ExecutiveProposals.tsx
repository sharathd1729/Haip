"use client";
// AI Executive, phase E2: plans waiting for the owner ("Needs your OK"), the exact preview of what each will do, Approve /
// Reject (owner only; the approval is bound to the plan the owner saw), other modules' approvals in one list, and what was
// done this week. Backend: POST /chief/proposals/{id}/approve|reject, GET /chief/home (proposals, activity, approvals).
import { useState } from "react";
import Link from "next/link";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { ArrowRight, Check, Loader2 } from "@/lib/icons";
import { useToast } from "@/components/ui/toast";
import { Card, CardBody, CardHeader, Drawer, StatusPill } from "@/components/ui/kit";
import {
  DISMISS_LABEL, PROPOSAL_STATUS_LABEL, PROPOSAL_STATUS_TONE, TIER_LABEL, sinceText,
  type ApprovalItem, type ChiefProposal, type DismissReason,
} from "./types";

const REASONS: DismissReason[] = ["not_now", "wrong", "already_handled", "not_worth_it", "too_risky"];
const pill = "inline-flex min-h-[44px] items-center gap-2 rounded-full px-4 text-sm font-semibold disabled:opacity-60";
const STEP_MARK: Record<string, string> = { done: "Done", waiting: "Waiting", failed: "Stopped", pending: "To do" };

function errorText(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof d === "string" ? d : "Try again.";
}

function ProposalDrawer({ p, isOwner, onClose }: { p: ChiefProposal | null; isOwner: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const done = () => { qc.invalidateQueries({ queryKey: ["chief-home"] }); onClose(); };
  const approve = useMutation({
    mutationFn: () => api.post(`/chief/proposals/${p!.id}/approve`, { plan_sha: p!.plan_sha }).then(r => r.data),
    onSuccess: () => { toast({ variant: "success", title: "Approved", description: "The Executive starts now and tells you when it is done." }); done(); },
    onError: e => toast({ variant: "error", title: "Couldn't approve", description: errorText(e) }),
  });
  const reject = useMutation({
    mutationFn: (reason: DismissReason) => api.post(`/chief/proposals/${p!.id}/reject`, { reason }).then(r => r.data),
    onSuccess: () => { toast({ variant: "success", title: "Okay, it won't do this", description: "Not suggested again for 7 days." }); done(); },
    onError: e => toast({ variant: "error", title: "Couldn't save", description: errorText(e) }),
  });
  const open = p?.status === "awaiting_approval";
  return (
    <Drawer open={p !== null} onOpenChange={o => !o && onClose()} title={p?.title ?? ""}
      description={p ? `${PROPOSAL_STATUS_LABEL[p.status]} · ${TIER_LABEL[p.risk_tier]}` : undefined}>
      {p && (
        <div className="space-y-4">
          <section>
            <p className="text-xs font-semibold uppercase tracking-wide text-[var(--haip-fg-subtle)]">Why</p>
            <p className="mt-1 text-sm text-[var(--haip-fg)]">{p.why}</p>
          </section>
          <section className="rounded-xl bg-[var(--haip-surface)] p-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-[var(--haip-fg-subtle)]">What will happen</p>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-[var(--haip-fg)]">
              {p.preview.map((line, i) => <li key={i}>{line}</li>)}
            </ul>
          </section>
          <section>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--haip-fg-subtle)]">Steps</p>
            <ol className="space-y-2">
              {p.steps.map((s, i) => (
                <li key={i} className="flex items-start justify-between gap-3 rounded-xl border border-[var(--haip-border)] p-3">
                  <span className="min-w-0">
                    <span className="block text-sm text-[var(--haip-fg)]">{i + 1}. {s.label}</span>
                    {s.reason && <span className="mt-0.5 block text-xs text-[var(--haip-fg-muted)]">{s.reason}</span>}
                  </span>
                  <StatusPill tone={s.status === "done" ? "success" : s.status === "failed" ? "danger" : s.status === "waiting" ? "warning" : "neutral"}
                    className="shrink-0">{STEP_MARK[s.status ?? "pending"]}</StatusPill>
                </li>
              ))}
            </ol>
          </section>
          {p.failure && <p className="rounded-xl bg-[var(--haip-status-danger-bg)] p-3 text-sm text-[var(--haip-status-danger-fg)]">{p.failure}</p>}
          {p.decided_at && (
            <p className="text-xs text-[var(--haip-fg-subtle)]">
              Decided {sinceText(p.decided_at)}{p.decided_via === "whatsapp" ? " on WhatsApp" : ""}.
            </p>
          )}
          {open && (isOwner ? (
            <section className="space-y-3 border-t border-[var(--haip-border)] pt-4">
              {p.app_only && <p className="text-xs text-[var(--haip-fg-muted)]">This reaches guests or money, so it can only be approved here.</p>}
              <button type="button" disabled={approve.isPending} onClick={() => approve.mutate()} className={cn(pill, "w-full justify-center bg-primary text-primary-foreground sm:w-auto")}>
                {approve.isPending ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />} Approve and start
              </button>
              <div>
                <p className="mb-2 text-sm font-semibold text-[var(--haip-fg)]">Or say no, and why</p>
                <div className="flex flex-wrap gap-2">
                  {REASONS.map(r => (
                    <button key={r} type="button" disabled={reject.isPending} onClick={() => reject.mutate(r)}
                      className={cn(pill, "border border-[var(--haip-border)] text-[var(--haip-fg-muted)] hover:bg-[var(--haip-surface)]")}>
                      {DISMISS_LABEL[r]}
                    </button>
                  ))}
                </div>
              </div>
            </section>
          ) : <p className="border-t border-[var(--haip-border)] pt-4 text-sm text-[var(--haip-fg-muted)]">Only an owner can approve this.</p>)}
        </div>
      )}
    </Drawer>
  );
}

function ProposalRow({ p, onOpen }: { p: ChiefProposal; onOpen: (p: ChiefProposal) => void }) {
  return (
    <li>
      <button type="button" onClick={() => onOpen(p)} className="flex min-h-[44px] w-full items-start gap-3 py-3 text-left">
        <StatusPill tone={PROPOSAL_STATUS_TONE[p.status]} className="mt-0.5 shrink-0">{PROPOSAL_STATUS_LABEL[p.status]}</StatusPill>
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-semibold text-[var(--haip-fg)]">{p.title}</span>
          <span className="mt-0.5 line-clamp-2 block text-sm text-[var(--haip-fg-muted)]">{p.failure || p.why}</span>
        </span>
        <ArrowRight size={14} className="mt-1 shrink-0 text-[var(--haip-fg-subtle)]" />
      </button>
    </li>
  );
}

export function NeedsYourOk({ proposals, approvals, isOwner }: { proposals: ChiefProposal[]; approvals: ApprovalItem[]; isOwner: boolean }) {
  const [open, setOpen] = useState<ChiefProposal | null>(null);
  if (proposals.length === 0 && approvals.length === 0) return null;
  return (
    <Card>
      <CardHeader title="Needs your OK" description={`${proposals.length + approvals.length} waiting`} tone="olive" />
      <CardBody>
        <ul className="divide-y divide-[var(--haip-border)]">
          {proposals.map(p => <ProposalRow key={p.id} p={p} onOpen={setOpen} />)}
          {approvals.map(a => (
            <li key={`${a.source}-${a.id}`}>
              <Link href={a.href ?? "/dashboard/analyst"} className="flex min-h-[44px] items-start gap-3 py-3">
                <StatusPill tone="neutral" className="mt-0.5 shrink-0">{a.source === "marketing" ? "Marketing" : "AI change"}</StatusPill>
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-semibold text-[var(--haip-fg)]">{a.title}</span>
                  <span className="mt-0.5 block text-sm text-[var(--haip-fg-muted)]">{a.detail}</span>
                </span>
                <ArrowRight size={14} className="mt-1 shrink-0 text-[var(--haip-fg-subtle)]" />
              </Link>
            </li>
          ))}
        </ul>
      </CardBody>
      <ProposalDrawer p={open} isOwner={isOwner} onClose={() => setOpen(null)} />
    </Card>
  );
}

export function DoneThisWeek({ items, isOwner }: { items: ChiefProposal[]; isOwner: boolean }) {
  const [open, setOpen] = useState<ChiefProposal | null>(null);
  if (items.length === 0) return null;
  return (
    <Card>
      <CardHeader title="What the Executive did" description="last 7 days and still running" tone="plain" />
      <CardBody>
        <ul className="divide-y divide-[var(--haip-border)]">
          {items.map(p => <ProposalRow key={p.id} p={p} onOpen={setOpen} />)}
        </ul>
      </CardBody>
      <ProposalDrawer p={open} isOwner={isOwner} onClose={() => setOpen(null)} />
    </Card>
  );
}
