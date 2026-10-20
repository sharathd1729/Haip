"use client";
// Lead workflows: the ready-made playbooks that make sure no lead goes unnoticed (missed call -> WhatsApp, no answer ->
// WhatsApp, "Call me back" -> task), their WhatsApp templates and what they did recently.
// Backend: GET /workflows/catalog, PUT /workflows/settings, POST /workflows/templates/lead-pack, GET /workflows/activity
// (owner/manager; settings changes are audited). Every playbook is off until switched on here.
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Loader2 } from "@/lib/icons";
import { useToast } from "@/components/ui/toast";
import { Card, CardBody, CardHeader, EmptyState, PageHeader, StatusPill, type Tone } from "@/components/ui/kit";

interface Playbook {
  key: string; code: string; name: string; kind: string; built: boolean;
  trigger: string; actions: string[]; stops: string;
  settings: { enabled: boolean; [k: string]: unknown };
  template: { name: string; status: string | null; in_pack: boolean } | null;
  today: Record<string, number>;
}
interface Template { name: string; label: string; when: string; body: string; buttons: string[]; status: string | null; rejection_reason: string | null }
interface Catalog {
  enabled: boolean; guest_cap_hours: number; daily_cap: number;
  playbooks: Playbook[]; templates: Template[]; conflicts: string[];
}
interface Activity {
  id: string; playbook_name: string; action: string; status: string; reason: string | null;
  template: string | null; inquiry_id: string | null; guest_name: string | null; at: string | null;
}

const TEMPLATE_TONE: Record<string, Tone> = { approved: "success", pending: "info", draft: "neutral", rejected: "danger", submission_failed: "danger" };
const TEMPLATE_LABEL: Record<string, string> = { approved: "Approved", pending: "With Meta", draft: "Draft", rejected: "Rejected", submission_failed: "Not submitted" };
const ACTION_LABEL: Record<string, string> = { wa_template: "WhatsApp template", wa_text: "WhatsApp message", task: "Callback task", push: "Push", staff_wa: "Staff alert" };
const STATUS_TONE: Record<string, Tone> = { queued: "success", done: "success", skipped: "warning", failed: "danger" };
const STATUS_LABEL: Record<string, string> = { queued: "Sent", done: "Done", skipped: "Skipped", failed: "Failed" };

const fmt = new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });

function errorText(e: unknown, fallback: string): string {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === "string" ? detail : fallback;
}

function Switch({ on, label, disabled, onChange }: { on: boolean; label: string; disabled?: boolean; onChange: (v: boolean) => void }) {
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={label} disabled={disabled} onClick={() => onChange(!on)}
      className="inline-flex min-h-[44px] min-w-[44px] items-center justify-center disabled:cursor-not-allowed disabled:opacity-50">
      <span className={cn("relative block h-6 w-11 rounded-full transition-colors", on ? "bg-primary" : "bg-[var(--haip-border-strong,var(--haip-border))]")}>
        <span className={cn("absolute left-0 top-0.5 h-5 w-5 rounded-full bg-[var(--haip-card)] shadow transition-transform", on ? "translate-x-[22px]" : "translate-x-0.5")} />
      </span>
    </button>
  );
}

function TemplatePill({ status }: { status: string | null }) {
  if (!status) return <StatusPill tone="warning">Template not created</StatusPill>;
  return <StatusPill tone={TEMPLATE_TONE[status] ?? "neutral"}>Template: {TEMPLATE_LABEL[status] ?? status}</StatusPill>;
}

export default function WorkflowsPage() {
  const { data: session } = useSession();
  const role = session?.user?.role;
  const canView = role === "owner" || role === "manager";
  const qc = useQueryClient();
  const { toast } = useToast();

  const catalog = useQuery<Catalog>({
    queryKey: ["workflows-catalog"], queryFn: () => api.get("/workflows/catalog").then(r => r.data), enabled: canView,
  });
  const activity = useQuery<{ items: Activity[] }>({
    queryKey: ["workflows-activity"], queryFn: () => api.get("/workflows/activity", { params: { limit: 30 } }).then(r => r.data),
    enabled: canView,
  });

  const save = useMutation({
    mutationFn: (patch: Record<string, unknown>) => api.put("/workflows/settings", patch).then(r => r.data as Catalog),
    onSuccess: fresh => { qc.setQueryData(["workflows-catalog"], fresh); toast({ variant: "success", title: "Saved" }); },
    onError: e => toast({ variant: "error", title: "Couldn't save", description: errorText(e, "Try again.") }),
  });
  const createPack = useMutation({
    mutationFn: () => api.post("/workflows/templates/lead-pack").then(r => r.data as { created: string[] }),
    onSuccess: res => {
      qc.invalidateQueries({ queryKey: ["workflows-catalog"] });
      toast({ variant: "success", title: res.created.length ? "Templates added as drafts" : "Templates already there",
        description: res.created.length ? "Open each one in Templates and submit it to Meta." : undefined });
    },
    onError: e => toast({ variant: "error", title: "Couldn't add the templates", description: errorText(e, "Try again.") }),
  });

  if (!canView) {
    return <div className="p-8 text-sm text-[var(--haip-fg-muted)]">Only an owner or manager can see lead workflows.</div>;
  }
  if (catalog.isPending || catalog.isError || !catalog.data) {
    return (
      <div className="flex items-center gap-2 p-8 text-sm text-[var(--haip-fg-muted)]">
        {catalog.isError ? "Couldn't load lead workflows. Refresh to try again." : <><Loader2 size={16} className="animate-spin" /> Loading…</>}
      </div>
    );
  }
  const data = catalog.data;
  const live = data.playbooks.filter(p => p.built);
  const next = data.playbooks.filter(p => !p.built);
  const missingTemplates = data.templates.some(t => !t.status);
  const toggle = (key: string, enabled: boolean) => save.mutate({ playbooks: { [key]: { enabled } } });

  return (
    <div className="h-full overflow-y-auto bg-[var(--haip-bg,var(--background))]">
      <div className="mx-auto max-w-3xl space-y-5 px-4 py-6 sm:px-6">
        <PageHeader title="Lead workflows"
          subtitle="Automatic steps so no lead goes unnoticed. Each one is off until you switch it on." />

        <Card>
          <CardBody className="flex items-center justify-between gap-4 pt-4">
            <div className="min-w-0">
              <p className="text-sm font-semibold text-[var(--haip-fg)]">Workflows for this workspace</p>
              <p className="text-xs text-[var(--haip-fg-subtle)]">
                At most one automatic WhatsApp per guest every {data.guest_cap_hours} h, and {data.daily_cap} a day in total.
              </p>
            </div>
            <Switch on={data.enabled} label="Workflows for this workspace" disabled={save.isPending} onChange={v => save.mutate({ enabled: v })} />
          </CardBody>
        </Card>

        {data.conflicts.length > 0 && (
          <Card className="border-[var(--haip-status-warning-border)]">
            <CardBody className="pt-4 text-sm text-[var(--haip-fg)]">
              <p className="font-semibold">An older automation also messages guests after calls.</p>
              <p className="mt-1 text-[13px] text-[var(--haip-fg-muted)]">
                Turn off {data.conflicts.map(n => `“${n}”`).join(", ")} in <Link className="text-primary underline" href="/dashboard/automations">Automations</Link>,
                or the missed-call and no-answer messages stay paused so guests never get two.
              </p>
            </CardBody>
          </Card>
        )}

        <Card>
          <CardHeader title="WhatsApp templates"
            description="A phone call does not open WhatsApp's 24-hour window, so these messages usually need an approved template."
            actions={missingTemplates ? (
              <button type="button" onClick={() => createPack.mutate()} disabled={createPack.isPending}
                className="inline-flex min-h-[44px] items-center gap-2 rounded-full bg-primary px-4 text-sm font-semibold text-primary-foreground disabled:opacity-60">
                {createPack.isPending && <Loader2 size={14} className="animate-spin" />} Create templates
              </button>
            ) : (
              <Link href="/dashboard/messaging/templates" className="inline-flex min-h-[44px] items-center text-sm font-semibold text-primary">Open templates</Link>
            )} />
          <CardBody className="space-y-3">
            {data.templates.map(t => (
              <div key={t.name} className="rounded-xl border border-[var(--haip-border)] p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-semibold text-[var(--haip-fg)]">{t.label}</span>
                  <TemplatePill status={t.status} />
                </div>
                <p className="mt-1.5 text-[13px] leading-relaxed text-[var(--haip-fg-muted)]">{t.body}</p>
                <p className="mt-1.5 text-xs text-[var(--haip-fg-subtle)]">Buttons: {t.buttons.join(" · ")}</p>
                {t.rejection_reason && <p className="mt-1 text-xs text-[var(--haip-status-danger-fg)]">Meta: {t.rejection_reason}</p>}
              </div>
            ))}
          </CardBody>
        </Card>

        <section className="space-y-3" aria-label="Playbooks">
          {live.map(p => {
            const sent = (p.today.queued ?? 0) + (p.today.done ?? 0);
            const skipped = p.today.skipped ?? 0;
            return (
              <Card key={p.key}>
                <CardHeader title={p.name} description={p.trigger}
                  actions={<Switch on={p.settings.enabled} label={p.name} disabled={save.isPending || !data.enabled} onChange={v => toggle(p.key, v)} />} />
                <CardBody>
                  <ul className="list-disc space-y-1 pl-5 text-[13px] text-[var(--haip-fg-muted)]">
                    {p.actions.map(a => <li key={a}>{a}</li>)}
                  </ul>
                  <p className="mt-2 text-xs text-[var(--haip-fg-subtle)]">Skips when: {p.stops}</p>
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    {p.template && <TemplatePill status={p.template.status} />}
                    <StatusPill tone="neutral">Today: {sent} done{skipped ? `, ${skipped} skipped` : ""}</StatusPill>
                  </div>
                </CardBody>
              </Card>
            );
          })}
        </section>

        <Card>
          <CardHeader title="Coming next" description="Planned playbooks. They switch on here once they ship." />
          <CardBody className="divide-y divide-[var(--haip-border)]">
            {next.map(p => (
              <div key={p.key} className="py-2.5">
                <p className="text-sm font-semibold text-[var(--haip-fg)]">{p.name}</p>
                <p className="text-xs text-[var(--haip-fg-subtle)]">{p.trigger}</p>
              </div>
            ))}
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Recent activity" description="What the workflows did or skipped, newest first. Times in IST." />
          <CardBody>
            {activity.isPending ? (
              <p className="flex items-center gap-2 text-sm text-[var(--haip-fg-muted)]"><Loader2 size={14} className="animate-spin" /> Loading…</p>
            ) : activity.isError ? (
              <p className="text-sm text-[var(--haip-fg-muted)]">Couldn&apos;t load the activity. Refresh to try again.</p>
            ) : !activity.data?.items.length ? (
              <EmptyState title="Nothing yet" hint="When a switched-on workflow runs, each message, task and skip shows here with the reason." />
            ) : (
              <ul className="divide-y divide-[var(--haip-border)]">
                {activity.data.items.map(a => (
                  <li key={a.id} className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1 py-2.5">
                    <div className="min-w-0 flex-1">
                      <p className="text-sm text-[var(--haip-fg)]">
                        {a.inquiry_id ? <Link href={`/dashboard/leads/${a.inquiry_id}`} className="font-semibold text-primary">{a.guest_name || "Guest"}</Link>
                          : <span className="font-semibold">{a.guest_name || "Guest"}</span>}
                        {" · "}{ACTION_LABEL[a.action] ?? a.action}
                      </p>
                      <p className="text-xs text-[var(--haip-fg-subtle)]">{a.playbook_name}{a.reason ? ` — ${a.reason}` : ""}</p>
                    </div>
                    <div className="flex items-center gap-2">
                      <StatusPill tone={STATUS_TONE[a.status] ?? "neutral"}>{STATUS_LABEL[a.status] ?? a.status}</StatusPill>
                      <span className="text-xs tabular-nums text-[var(--haip-fg-subtle)]">{a.at ? fmt.format(new Date(a.at)) : ""}</span>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </CardBody>
        </Card>
      </div>
    </div>
  );
}
