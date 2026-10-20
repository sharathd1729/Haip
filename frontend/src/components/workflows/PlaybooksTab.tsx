"use client";
// Lead workflows, Playbooks tab: the switches, modes, team alerts and the WhatsApp templates the playbooks send.
// Backend: GET /workflows/catalog, PUT /workflows/settings, POST /workflows/templates/lead-pack, GET /workflows/alerts/recipients
// (owner/manager; settings changes are audited). Every playbook is off until switched on here.
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { Loader2 } from "@/lib/icons";
import { useToast } from "@/components/ui/toast";
import { Card, CardBody, CardHeader, StatusPill, type Tone } from "@/components/ui/kit";
import { Switch } from "@/components/workflows/Switch";

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
  staff_whatsapp: boolean; quiet_start_hour: number; quiet_end_hour: number;
  playbooks: Playbook[]; templates: Template[]; conflicts: string[];
}
interface Person { id: string; name: string; role: string; has_phone: boolean; whatsapp_opt_in: boolean; channel: "whatsapp" | "push" }

const TEMPLATE_TONE: Record<string, Tone> = { approved: "success", pending: "info", draft: "neutral", rejected: "danger", submission_failed: "danger" };
const TEMPLATE_LABEL: Record<string, string> = { approved: "Approved", pending: "With Meta", draft: "Draft", rejected: "Rejected", submission_failed: "Not submitted" };
const MODES = [
  { id: "tasks", title: "Tasks only", desc: "A reminder for the lead's owner. Nothing goes to the guest." },
  { id: "drafts", title: "AI drafts", desc: "An AI draft to approve in the inbox (or the template to send when the chat window is closed)." },
  { id: "autopilot", title: "Automatic", desc: "Our fixed wording goes by itself, 9:30 am to 8 pm. Never AI text." },
] as const;
const HOURS = Array.from({ length: 24 }, (_, h) => h);
const hourLabel = (h: number) => `${h % 12 || 12}:00 ${h < 12 ? "am" : "pm"}`;
const selectCls = "min-h-[44px] rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-2.5 text-[16px] text-[var(--haip-fg)] sm:text-sm";


function errorText(e: unknown, fallback: string): string {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === "string" ? detail : fallback;
}

function TemplatePill({ status }: { status: string | null }) {
  if (!status) return <StatusPill tone="warning">Template not created</StatusPill>;
  return <StatusPill tone={TEMPLATE_TONE[status] ?? "neutral"}>Template: {TEMPLATE_LABEL[status] ?? status}</StatusPill>;
}

export function PlaybooksTab() {
  const qc = useQueryClient();
  const { toast } = useToast();

  const catalog = useQuery<Catalog>({
    queryKey: ["workflows-catalog"], queryFn: () => api.get("/workflows/catalog").then(r => r.data),
  });

  const people = useQuery<{ people: Person[] }>({
    queryKey: ["workflows-alert-people"], queryFn: () => api.get("/workflows/alerts/recipients").then(r => r.data),
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
    <div className="space-y-5">

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
                  {typeof p.settings.mode === "string" && (
                    <div className="mt-3">
                      <p className="mb-1.5 text-xs font-semibold text-[var(--haip-fg)]">How messages to the guest go</p>
                      <div className="grid gap-2 sm:grid-cols-3" role="radiogroup" aria-label={`${p.name}: mode`}>
                        {MODES.map(m => {
                          const on = p.settings.mode === m.id;
                          return (
                            <button key={m.id} type="button" role="radio" aria-checked={on} disabled={save.isPending}
                              onClick={() => save.mutate({ playbooks: { [p.key]: { mode: m.id } } })}
                              className={on ? "min-h-[44px] rounded-xl border border-primary bg-[var(--haip-primary-tint)] p-2.5 text-left"
                                : "min-h-[44px] rounded-xl border border-[var(--haip-border)] p-2.5 text-left hover:bg-[var(--haip-surface)]"}>
                              <span className="block text-sm font-semibold text-[var(--haip-fg)]">{m.title}</span>
                              <span className="block text-xs text-[var(--haip-fg-subtle)]">{m.desc}</span>
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  )}
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
          <CardHeader title="Team alerts"
            description="How the team hears about a lead that waits too long: the lead's owner first, then the managers, then the owners." />
          <CardBody className="space-y-1">
            <div className="flex items-center justify-between gap-4 border-b border-[var(--haip-border)] pb-2">
              <span className="min-w-0">
                <span className="block text-sm font-semibold text-[var(--haip-fg)]">WhatsApp the team</span>
                <span className="block text-xs text-[var(--haip-fg-subtle)]">To people who turned it on in their Profile. Everyone else gets app notifications.</span>
              </span>
              <Switch on={data.staff_whatsapp} label="WhatsApp the team" disabled={save.isPending} onChange={v => save.mutate({ staff_whatsapp: v })} />
            </div>
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--haip-border)] py-2">
              <span className="min-w-0">
                <span className="block text-sm font-semibold text-[var(--haip-fg)]">Quiet hours</span>
                <span className="block text-xs text-[var(--haip-fg-subtle)]">Alerts wait, then each person gets one morning summary.</span>
              </span>
              <span className="flex items-center gap-2 text-sm text-[var(--haip-fg-muted)]">
                <select aria-label="Quiet hours start" className={selectCls} value={data.quiet_start_hour} disabled={save.isPending}
                  onChange={e => save.mutate({ quiet_start_hour: Number(e.target.value) })}>
                  {HOURS.map(h => <option key={h} value={h}>{hourLabel(h)}</option>)}
                </select>
                to
                <select aria-label="Quiet hours end" className={selectCls} value={data.quiet_end_hour} disabled={save.isPending}
                  onChange={e => save.mutate({ quiet_end_hour: Number(e.target.value) })}>
                  {HOURS.map(h => <option key={h} value={h}>{hourLabel(h)}</option>)}
                </select>
              </span>
            </div>
            <p className="pt-2 text-xs font-semibold uppercase tracking-wide text-[var(--haip-fg-subtle)]">Who gets alerts</p>
            {people.isPending ? (
              <p className="text-sm text-[var(--haip-fg-muted)]">Loading…</p>
            ) : people.isError ? (
              <p className="text-sm text-[var(--haip-fg-muted)]">Couldn&apos;t load the team. Refresh to try again.</p>
            ) : !people.data?.people.length ? (
              <p className="text-sm text-[var(--haip-fg-muted)]">No team members yet.</p>
            ) : (
              <ul className="divide-y divide-[var(--haip-border)]">
                {people.data.people.map(p => (
                  <li key={p.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                    <span className="min-w-0 text-sm text-[var(--haip-fg)]">{p.name} <span className="text-xs capitalize text-[var(--haip-fg-subtle)]">· {p.role}</span></span>
                    {p.channel === "whatsapp" ? <StatusPill tone="success">WhatsApp + app</StatusPill>
                      : <StatusPill tone="neutral">{p.has_phone ? "App only: WhatsApp not turned on" : "App only: no phone on profile"}</StatusPill>}
                  </li>
                ))}
              </ul>
            )}
          </CardBody>
        </Card>

        {next.length > 0 && <Card>
          <CardHeader title="Coming next" description="Planned playbooks. They switch on here once they ship." />
          <CardBody className="divide-y divide-[var(--haip-border)]">
            {next.map(p => (
              <div key={p.key} className="py-2.5">
                <p className="text-sm font-semibold text-[var(--haip-fg)]">{p.name}</p>
                <p className="text-xs text-[var(--haip-fg-subtle)]">{p.trigger}</p>
              </div>
            ))}
          </CardBody>
        </Card>}

    </div>
  );
}
