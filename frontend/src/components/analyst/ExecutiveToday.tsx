"use client";
// AI Executive, phase E1 (read-only): today's brief headline, what needs the founder now (findings by role, worst first), and
// each finding's evidence, next step and a "not needed" reason; E2: plans waiting for the owner's OK and what was done.
// Backend: GET /chief/home, POST /chief/run, POST /chief/findings/{id}/dismiss, PUT /chief/settings (owner),
// POST /chief/templates. Nothing runs without an owner's approval.
import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { AlertTriangle, ArrowRight, CheckCircle2, Eye, Loader2, Pause, Play, RefreshCw, Sparkles } from "@/lib/icons";
import { useToast } from "@/components/ui/toast";
import { Card, CardBody, CardHeader, Drawer, EmptyState, Stat, StatusPill } from "@/components/ui/kit";
import {
  DISMISS_LABEL, KIND_LABEL, SEVERITY_LABEL, SEVERITY_TONE, periodText, sinceText,
  type ChiefFinding, type ChiefHome, type DismissReason,
} from "./types";
import { DoneThisWeek, NeedsYourOk } from "./ExecutiveProposals";

const REASONS: DismissReason[] = ["not_now", "already_handled", "wrong", "not_worth_it", "too_risky"];
const pill = "inline-flex min-h-[44px] items-center gap-2 rounded-full px-4 text-sm font-semibold disabled:opacity-60";

function FindingDrawer({ f, onClose }: { f: ChiefFinding | null; onClose: () => void }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const dismiss = useMutation({
    mutationFn: (reason: DismissReason) => api.post(`/chief/findings/${f!.id}/dismiss`, { reason }).then(r => r.data),
    onSuccess: (_, reason) => {
      qc.invalidateQueries({ queryKey: ["chief-home"] });
      toast({ variant: "success", title: "Hidden for 7 days", description: `Noted: ${DISMISS_LABEL[reason].toLowerCase()}.` });
      onClose();
    },
    onError: () => toast({ variant: "error", title: "Couldn't hide it", description: "Try again." }),
  });
  return (
    <Drawer open={f !== null} onOpenChange={o => !o && onClose()} title={f?.title ?? ""}
      description={f ? `${f.role_label} · seen since ${sinceText(f.first_seen_at)}` : undefined}>
      {f && (
        <div className="space-y-4">
          <StatusPill tone={SEVERITY_TONE[f.severity]}>{SEVERITY_LABEL[f.severity]}</StatusPill>
          <section>
            <p className="text-xs font-semibold uppercase tracking-wide text-[var(--haip-fg-subtle)]">Why it matters</p>
            <p className="mt-1 text-sm text-[var(--haip-fg)]">{f.why}</p>
          </section>
          {f.next_step && (
            <section className="rounded-xl bg-[var(--haip-surface)] p-3">
              <p className="text-xs font-semibold uppercase tracking-wide text-[var(--haip-fg-subtle)]">Next step</p>
              <p className="mt-1 text-sm font-semibold text-[var(--haip-fg)]">{f.next_step}</p>
            </section>
          )}
          {f.why !== f.body && f.body && <p className="text-xs text-[var(--haip-fg-muted)]">What HAIP measured: {f.body}</p>}
          <p className="text-[11px] text-[var(--haip-fg-subtle)]">
            {f.explained_by === "ai" ? "Found by a rule in HAIP; the AI wrote the explanation from the same numbers." : "Found and written by a rule in HAIP."}
          </p>
          {f.evidence.some(e => e.href) && (
            <section>
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--haip-fg-subtle)]">Records behind this ({f.evidence.length})</p>
              <ul className="flex flex-wrap gap-2">
                {f.evidence.filter(e => e.href).map((e, i) => (
                  <li key={e.id ?? i}>
                    <Link href={e.href!} className="inline-flex min-h-[44px] items-center rounded-full border border-[var(--haip-border)] px-3 text-sm text-primary hover:bg-[var(--haip-surface)]">
                      Open {e.type.replace(/_/g, " ")} {i + 1}
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          )}
          {f.cta_href && (
            <Link href={f.cta_href} className={cn(pill, "bg-primary text-primary-foreground")}>
              {f.cta_label ?? "Open"} <ArrowRight size={14} />
            </Link>
          )}
          <section className="border-t border-[var(--haip-border)] pt-4">
            <p className="mb-2 text-sm font-semibold text-[var(--haip-fg)]">Not needed? Tell the Executive why</p>
            <p className="mb-3 text-xs text-[var(--haip-fg-muted)]">It is hidden for 7 days. Your reason teaches it what to raise next time.</p>
            <div className="flex flex-wrap gap-2">
              {REASONS.map(r => (
                <button key={r} type="button" disabled={dismiss.isPending} onClick={() => dismiss.mutate(r)}
                  className={cn(pill, "border border-[var(--haip-border)] text-[var(--haip-fg-muted)] hover:bg-[var(--haip-surface)]")}>
                  {DISMISS_LABEL[r]}
                </button>
              ))}
            </div>
          </section>
        </div>
      )}
    </Drawer>
  );
}

export function ExecutiveToday({ isOwner, onOpenBrief }: { isOwner: boolean; onOpenBrief: () => void }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [open, setOpen] = useState<ChiefFinding | null>(null);
  const home = useQuery<ChiefHome>({ queryKey: ["chief-home"], queryFn: () => api.get("/chief/home").then(r => r.data), refetchInterval: 60000 });
  const save = useMutation({
    mutationFn: (patch: Partial<ChiefHome["settings"]>) => api.put("/chief/settings", { ...home.data!.settings, ...patch }).then(r => r.data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["chief-home"] }); setTimeout(() => qc.invalidateQueries({ queryKey: ["chief-home"] }), 15000); },
    onError: () => toast({ variant: "error", title: "Couldn't save", description: "Try again." }),
  });
  const template = useMutation({
    mutationFn: () => api.post("/chief/templates").then(r => r.data),
    onSuccess: () => toast({ variant: "success", title: "Approval template added as a draft", description: "Submit it to Meta from Messaging > Templates. WhatsApp approvals start once Meta approves it." }),
    onError: () => toast({ variant: "error", title: "Couldn't add the template", description: "Try again." }),
  });
  const run = useMutation({
    mutationFn: () => api.post("/chief/run").then(r => r.data),
    onSuccess: () => {
      toast({ variant: "success", title: "Checking now", description: "New findings appear here in a minute." });
      setTimeout(() => qc.invalidateQueries({ queryKey: ["chief-home"] }), 20000);
    },
    onError: () => toast({ variant: "error", title: "Couldn't start the check", description: "Try again." }),
  });

  if (home.isPending) return <div className="flex items-center gap-2 p-6 text-sm text-[var(--haip-fg-muted)]"><Loader2 size={16} className="animate-spin" /> Loading…</div>;
  if (home.isError || !home.data) return <p className="p-6 text-sm text-[var(--haip-fg-muted)]">Couldn&apos;t load the Executive. Refresh to try again.</p>;
  const h = home.data;

  if (!h.settings.enabled) {
    return (
      <Card>
        <EmptyState title="The AI Executive is off"
          hint="When it is on, it checks sales, the front desk, ops, payments, ads and integrations every few minutes, tells you what needs you, and suggests fixes. Nothing is changed until you approve it."
          action={isOwner
            ? <button type="button" disabled={save.isPending} onClick={() => save.mutate({ enabled: true })} className={cn(pill, "mt-3 bg-primary text-primary-foreground")}>
                {save.isPending ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />} Turn it on
              </button>
            : <p className="mt-2 text-sm text-[var(--haip-fg-muted)]">Ask the owner to turn it on.</p>} />
      </Card>
    );
  }

  const now = h.counts.critical + h.counts.high;
  return (
    <div className="space-y-4">
      <Card>
        <CardBody className="space-y-4 pt-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-[var(--haip-fg-muted)]">
              {h.last_checked_at ? `Last checked ${sinceText(h.last_checked_at)}` : "Not checked yet"}
              {h.settings.paused && <StatusPill tone="warning" className="ml-2">Paused: rules only, no AI write-ups</StatusPill>}
            </p>
            <div className="flex flex-wrap gap-2">
              {isOwner && (
                <button type="button" disabled={save.isPending} onClick={() => save.mutate({ paused: !h.settings.paused })}
                  className={cn(pill, "border border-[var(--haip-border)] text-[var(--haip-fg)]")}>
                  {h.settings.paused ? <><Play size={14} /> Resume</> : <><Pause size={14} /> Pause</>}
                </button>
              )}
              <button type="button" disabled={run.isPending} onClick={() => run.mutate()} className={cn(pill, "bg-primary text-primary-foreground")}>
                <RefreshCw size={14} className={cn(run.isPending && "animate-spin")} /> Check now
              </button>
            </div>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Stat label="Needs you now" value={now} hint="open now" icon={AlertTriangle} />
            <Stat label="To watch" value={h.counts.medium + h.counts.low + h.counts.info} hint="open now" icon={Eye} />
            <Stat label="Sorted by itself" value={h.counts.resolved_7d} hint="last 7 days" icon={CheckCircle2} />
          </div>
        </CardBody>
      </Card>

      {isOwner && (
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" disabled={save.isPending} onClick={() => save.mutate({ whatsapp_approvals: !h.settings.whatsapp_approvals })}
            className={cn(pill, "border border-[var(--haip-border)] text-[var(--haip-fg)]")} aria-pressed={h.settings.whatsapp_approvals}>
            Ask me on WhatsApp too: {h.settings.whatsapp_approvals ? "On" : "Off"}
          </button>
          {h.settings.whatsapp_approvals && (
            <button type="button" disabled={template.isPending} onClick={() => template.mutate()} className={cn(pill, "text-primary")}>
              Add the WhatsApp approval template
            </button>
          )}
        </div>
      )}

      <NeedsYourOk proposals={h.proposals ?? []} approvals={h.approvals ?? []} isOwner={isOwner} />

      <Card>
        <CardHeader title="Today's brief" tone="plain" description={h.brief ? `${KIND_LABEL[h.brief.kind]} · ${periodText(h.brief.period)}` : undefined} />
        <CardBody>
          {h.brief ? (
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <p className="font-[family-name:var(--font-display)] text-base font-semibold text-[var(--haip-fg)]">{h.brief.headline || "No headline"}</p>
              <button type="button" onClick={onOpenBrief} className={cn(pill, "shrink-0 border border-[var(--haip-border)] text-primary")}>
                Read it <ArrowRight size={14} />
              </button>
            </div>
          ) : (
            <p className="text-sm text-[var(--haip-fg-muted)]">No daily pulse yet. Switch on the analyst&apos;s daily pulse to get one every morning with these findings in it.</p>
          )}
        </CardBody>
      </Card>

      {h.roles.length === 0 ? (
        <Card><EmptyState title="Nothing needs you right now" hint="The Executive keeps checking every few minutes." /></Card>
      ) : h.roles.map(role => (
        <Card key={role.key}>
          <CardHeader title={role.label} description={`${role.findings.length} open`} />
          <CardBody>
            <ul className="divide-y divide-[var(--haip-border)]">
              {role.findings.map(f => (
                <li key={f.id}>
                  <button type="button" onClick={() => setOpen(f)}
                    className="flex min-h-[44px] w-full items-start gap-3 py-3 text-left">
                    <StatusPill tone={SEVERITY_TONE[f.severity]} className="mt-0.5 shrink-0">{SEVERITY_LABEL[f.severity]}</StatusPill>
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm font-semibold text-[var(--haip-fg)]">{f.title}</span>
                      {f.why && <span className="mt-0.5 line-clamp-2 block text-sm text-[var(--haip-fg-muted)]">{f.why}</span>}
                    </span>
                    <ArrowRight size={14} className="mt-1 shrink-0 text-[var(--haip-fg-subtle)]" />
                  </button>
                </li>
              ))}
            </ul>
          </CardBody>
        </Card>
      ))}
      <DoneThisWeek items={h.activity ?? []} isOwner={isOwner} />
      <FindingDrawer f={open} onClose={() => setOpen(null)} />
    </div>
  );
}
