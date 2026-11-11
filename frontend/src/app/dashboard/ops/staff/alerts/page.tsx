"use client";
// Ops › Staff › If nobody answers (owner pick "A", 8 Nov 2026): the alert chain of one duty as a ladder, with a severity
// switch. Who each step reaches right now comes from GET /ops/on-duty `steps` (roster_service decides, never this page);
// the wait between steps is the severity's "ack within" minutes from GET /ops/settings. The owner is always the last step.
// Writes: PUT/DELETE /ops/escalation-chains, PUT /ops/settings (ops.manage, audited on the server).
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { useHydrated } from "@/lib/bookingAgenda";
import { canManageOps, DUTY_LABELS, type OpsStaff } from "@/lib/ops";
import {
  chainTimes, DEFAULT_ACK, DUTY_ORDER, editableSteps, isOwnerStep, minutesLabel, moveStep, SEVERITIES, SEVERITY_LABELS, stepWords, withOwnerLast,
  type ChainSpec, type OnDuty, type OpsSettings, type Severity,
} from "@/lib/opsRoster";
import { ChevronDown, ChevronUp, Lock, Moon, X, Zap } from "@/lib/icons";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardBody, CardHeader, ChipRow, EmptyState, PageHeader } from "@/components/ui/kit";
import { OpsNav } from "@/components/ops/OpsNav";
import { StaffTabs } from "@/components/ops/StaffTabs";
import { input, label } from "@/components/ops/TripSheets";

interface Chains { chains: { id: string; duty: string; property_id: string | null; steps: ChainSpec[] }[] }
const ADD_OPTIONS: { value: string; label: string; spec: ChainSpec }[] = [
  { value: "on_shift", label: "Whoever is on shift", spec: { type: "on_shift" } },
  { value: "ops_manager", label: "Ops manager on shift", spec: { type: "on_shift", duty: "ops_manager" } },
  { value: "duty", label: "Anyone who does this job (backup)", spec: { type: "duty" } },
  { value: "manager", label: "Managers", spec: { type: "role", role: "manager" } },
];

function errorText(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof d === "string" ? d : "Check your connection and try again.";
}
const plus = (m: number) => (m === 0 ? "At once" : m < 60 ? `+${m} min` : m % 60 ? `+${Math.floor(m / 60)} h ${m % 60} min` : `+${m / 60} h`);

export default function IfNobodyAnswersPage() {
  const hydrated = useHydrated();
  const qc = useQueryClient();
  const { toast } = useToast();
  const session = useSession();
  const manage = canManageOps(session.data?.user?.role);
  const [duty, setDuty] = useState("caretaker");
  const [sev, setSev] = useState<Severity>("high");
  const [editing, setEditing] = useState<ChainSpec[] | null>(null);
  const [adding, setAdding] = useState("");
  const [form, setForm] = useState<{ ack: Record<Severity, string>; start: string; end: string } | null>(null);

  const staffQ = useQuery<OpsStaff[]>({ queryKey: ["ops-staff", "all"], queryFn: () => api.get("/ops/staff?include_inactive=true").then(r => r.data), staleTime: 30_000, enabled: manage });
  const chainsQ = useQuery<Chains>({ queryKey: ["ops-chains"], queryFn: () => api.get("/ops/escalation-chains").then(r => r.data), enabled: manage });
  const settingsQ = useQuery<OpsSettings>({ queryKey: ["ops-settings"], queryFn: () => api.get("/ops/settings").then(r => r.data), enabled: manage });
  const dutyQ = useQuery<OnDuty>({
    queryKey: ["ops-on-duty", duty, sev],
    queryFn: () => api.get("/ops/on-duty", { params: { duty, severity: sev } }).then(r => r.data),
    enabled: manage, refetchInterval: 60_000,
  });

  const staff = useMemo(() => staffQ.data ?? [], [staffQ.data]);
  // Duties the team actually has come first in the chips; the rest follow so a chain can be set before anyone is added.
  const duties = useMemo(() => {
    const held = DUTY_ORDER.filter(d => staff.some(s => s.active && s.duties.some(x => x.duty === d)));
    return [...held, ...DUTY_ORDER.filter(d => !held.includes(d))];
  }, [staff]);
  useEffect(() => { if (staff.length && duties[0]) setDuty(d => (staff.some(s => s.duties.some(x => x.duty === d)) ? d : duties[0])); }, [staff, duties]);
  useEffect(() => {
    const s = settingsQ.data;
    if (s) setForm({ ack: Object.fromEntries(SEVERITIES.map(k => [k, String(s.sla[k]?.[0] ?? DEFAULT_ACK[k])])) as Record<Severity, string>, start: s.quiet_hours.start, end: s.quiet_hours.end });
  }, [settingsQ.data]);

  const ack = (k: Severity) => settingsQ.data?.sla[k]?.[0] ?? DEFAULT_ACK[k];
  const custom = chainsQ.data?.chains.find(c => c.duty === duty && !c.property_id);
  const steps = dutyQ.data?.steps ?? [];
  const times = chainTimes(steps, ack(sev));
  const nameOf = (id: string) => staff.find(s => s.id === id)?.name;

  const refresh = () => { qc.invalidateQueries({ queryKey: ["ops-on-duty"] }); qc.invalidateQueries({ queryKey: ["ops-chains"] }); };
  const fail = (e: unknown) => toast({ title: "Not saved", description: errorText(e), variant: "error" });
  const saveChain = useMutation({
    mutationFn: (list: ChainSpec[]) => api.put("/ops/escalation-chains", { duty, property_id: null, steps: withOwnerLast(list) }),
    onSuccess: () => { refresh(); setEditing(null); toast({ title: "Order saved", variant: "success" }); }, onError: fail,
  });
  const resetChain = useMutation({
    mutationFn: (id: string) => api.delete(`/ops/escalation-chains/${id}`),
    onSuccess: () => { refresh(); setEditing(null); toast({ title: "Back to the default order", variant: "success" }); }, onError: fail,
  });
  const saveSettings = useMutation({
    mutationFn: (f: NonNullable<typeof form>) => api.put("/ops/settings", {
      sla: Object.fromEntries(SEVERITIES.map(k => [k, [Number(f.ack[k]), settingsQ.data?.sla[k]?.[1] ?? 60]])),
      quiet_hours: { start: f.start, end: f.end },
    }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["ops-settings"] }); toast({ title: "Saved", variant: "success" }); }, onError: fail,
  });

  const addStep = (value: string) => {
    if (!editing || !value) return;
    const spec = value.startsWith("staff:") ? { type: "staff" as const, staff_id: value.slice(6) } : ADD_OPTIONS.find(o => o.value === value)?.spec;
    if (spec) setEditing([...editing, spec]);
    setAdding("");
  };
  const loading = !hydrated || session.status === "loading" || (manage && (staffQ.isPending || chainsQ.isPending || settingsQ.isPending));
  const failed = staffQ.isError || chainsQ.isError || settingsQ.isError;
  const dutyWord = (DUTY_LABELS[duty] ?? duty).toLowerCase();

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 p-4 sm:p-6">
      <PageHeader title="If nobody answers" subtitle="Who hears about a problem, and how long each person has to answer." />
      <OpsNav />
      <StaffTabs />
      {loading ? (
        <div className="flex flex-col gap-2" aria-busy="true"><Skeleton className="h-11" /><Skeleton className="h-14" /><Skeleton className="h-64" /></div>
      ) : !manage ? (
        <Card><EmptyState title="Only an owner or manager can change alerts" hint="Ask them if something should reach you." /></Card>
      ) : failed ? (
        <Card><EmptyState title="Couldn't load the alert settings" hint="Check your connection, then try again."
          action={<button type="button" className="haip-btn-primary min-h-12" onClick={() => { staffQ.refetch(); chainsQ.refetch(); settingsQ.refetch(); }}>Try again</button>} /></Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px] lg:items-start">
          <div className="flex min-w-0 flex-col gap-3">
            <ChipRow label="Duty" value={duty} onChange={d => { setDuty(d); setEditing(null); }} items={duties.map(d => ({ value: d, label: DUTY_LABELS[d] ?? d }))} />
            <div role="radiogroup" aria-label="Alert type" className="grid grid-cols-4 gap-1 rounded-2xl border border-[var(--haip-border)] bg-[var(--haip-card)] p-1">
              {SEVERITIES.map(k => (
                <button key={k} type="button" role="radio" aria-checked={sev === k} onClick={() => setSev(k)}
                  className={cn("flex min-h-12 flex-col items-center justify-center rounded-xl text-[14px] font-semibold leading-tight transition-colors active:scale-[0.97]",
                    sev === k ? "bg-[var(--haip-tab-active-bg)] text-[var(--haip-tab-active-fg)]" : "text-[var(--haip-fg)]")}>
                  {SEVERITY_LABELS[k]}<span className="num text-[11px] font-medium opacity-80">{minutesLabel(ack(k))}</span>
                </button>
              ))}
            </div>

            <Card className="p-0">
              <CardHeader title={DUTY_LABELS[duty] ?? duty} description={custom ? "Your own order" : "Default order"}
                actions={!editing && <button type="button" className="haip-btn-secondary min-h-11 px-4 text-[14px]" onClick={() => setEditing(editableSteps(steps.map(s => s.spec)))}>Change order</button>} />
              <CardBody className="px-3 py-3 sm:px-4">
                {dutyQ.isPending ? <Skeleton className="h-56" /> : dutyQ.isError ? (
                  <EmptyState title="Couldn't load who would be alerted" action={<button type="button" className="haip-btn-primary min-h-12" onClick={() => dutyQ.refetch()}>Try again</button>} />
                ) : editing ? (
                  <ol className="flex flex-col gap-2">
                    {editing.map((s, i) => (
                      <li key={`${i}-${s.type}-${s.duty ?? s.role ?? s.staff_id ?? ""}`} className="flex min-h-14 items-center gap-2 rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 py-1.5">
                        <span className="num grid size-7 shrink-0 place-items-center rounded-full bg-primary text-[12.5px] font-bold text-primary-foreground">{i + 1}</span>
                        <span className="min-w-0 flex-1 text-[15px] font-semibold">{stepWords(s, duty, nameOf)}</span>
                        <button type="button" aria-label="Move up" disabled={i === 0} onClick={() => setEditing(moveStep(editing, i, -1))} className="grid size-11 place-items-center rounded-xl text-primary disabled:opacity-30"><ChevronUp size={18} /></button>
                        <button type="button" aria-label="Move down" disabled={i === editing.length - 1} onClick={() => setEditing(moveStep(editing, i, 1))} className="grid size-11 place-items-center rounded-xl text-primary disabled:opacity-30"><ChevronDown size={18} /></button>
                        <button type="button" aria-label="Remove step" onClick={() => setEditing(editing.filter((_, j) => j !== i))} className="grid size-11 place-items-center rounded-xl text-[var(--haip-fg-subtle)]"><X size={18} /></button>
                      </li>
                    ))}
                    <li className="flex min-h-14 items-center gap-2 rounded-xl border border-dashed border-[var(--haip-border)] px-3 py-1.5">
                      <span className="num grid size-7 shrink-0 place-items-center rounded-full bg-[var(--haip-accent)] text-[12.5px] font-bold text-[var(--haip-on-accent)]">{editing.length + 1}</span>
                      <span className="flex-1 text-[15px] font-semibold">You (owner)</span>
                      <span className="inline-flex items-center gap-1 rounded-full bg-[var(--haip-band-bg)] px-2.5 py-1 text-[12px] font-semibold text-[var(--haip-fg-subtle)]"><Lock size={12} />Always last</span>
                    </li>
                    {editing.length < 7 && (
                      <label className={label}>Add a step before you
                        <select className={input} value={adding} onChange={e => addStep(e.target.value)}>
                          <option value="">Choose who…</option>
                          {ADD_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                          {staff.filter(s => s.active).map(s => <option key={s.id} value={`staff:${s.id}`}>{s.name}</option>)}
                        </select>
                      </label>
                    )}
                    <div className="mt-1 flex flex-wrap gap-2">
                      <button type="button" disabled={saveChain.isPending} className="haip-btn-primary min-h-12 flex-1 sm:flex-none" onClick={() => saveChain.mutate(editing)}>{saveChain.isPending ? "Saving…" : "Save order"}</button>
                      <button type="button" className="haip-btn-secondary min-h-12 flex-1 sm:flex-none" onClick={() => setEditing(null)}>Cancel</button>
                      {custom && <button type="button" disabled={resetChain.isPending} className="min-h-12 px-3 text-[14px] font-semibold text-primary" onClick={() => resetChain.mutate(custom.id)}>Use the default</button>}
                    </div>
                  </ol>
                ) : (
                  <ol className="relative flex flex-col">
                    {steps.map((s, i) => {
                      const owner = isOwnerStep(s.spec);
                      const skip = times[i] == null;
                      return (
                        <li key={s.step} className="relative grid grid-cols-[64px_1fr] gap-3">
                          <span aria-hidden className={cn("absolute bottom-0 left-[75px] w-0.5 bg-[var(--haip-band-border)]", i === 0 ? "top-6" : "top-0", i === steps.length - 1 && "bottom-auto h-6")} />
                          <span aria-hidden className={cn("absolute left-[69px] top-[19px] size-3.5 rounded-full border-[3px]",
                            owner ? "border-[var(--haip-accent)] bg-[var(--haip-accent)]" : skip ? "border-[var(--haip-border)] bg-[var(--haip-card)]" : "border-primary bg-[var(--haip-card)]")} />
                          <span className={cn("num pt-4 text-right text-[13px] font-bold", times[i] === 0 ? "text-[var(--haip-accent-ink)]" : skip ? "text-[var(--haip-fg-subtle)]" : "text-primary")}>
                            {skip ? "Skipped" : plus(times[i] as number)}
                          </span>
                          <div className={cn("my-1.5 ml-4 flex min-h-14 items-center gap-2 rounded-xl border px-3 py-2",
                            skip ? "border-dashed border-[var(--haip-border)]" : "border-[var(--haip-border)] bg-[var(--haip-card)]")}>
                            <div className="min-w-0 flex-1">
                              <div className="text-[12.5px] text-[var(--haip-fg-subtle)]">{stepWords(s.spec, duty, nameOf)}</div>
                              <div className={cn("text-[15px] font-semibold", skip && "font-medium text-[var(--haip-fg-subtle)]")}>
                                {owner ? "You" : s.recipients.length ? `Right now: ${s.recipients.join(", ")}` : "Nobody right now, so this step is skipped"}
                              </div>
                            </div>
                            {owner && <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-[var(--haip-band-bg)] px-2.5 py-1 text-[12px] font-semibold text-[var(--haip-fg-subtle)]"><Lock size={12} />Always last</span>}
                          </div>
                        </li>
                      );
                    })}
                  </ol>
                )}
              </CardBody>
            </Card>
            {sev === "critical" && (
              <p className="flex gap-2 rounded-xl bg-[var(--haip-accent-light)] p-3 text-[14px] text-[var(--haip-accent-ink)]"><Zap size={16} className="mt-0.5 shrink-0" />Critical also tells the ops manager on shift straight away, not after a wait.</p>
            )}
            {(sev === "normal" || sev === "low") && settingsQ.data && (
              <p className="flex gap-2 rounded-xl bg-[var(--haip-band-bg)] p-3 text-[14px] text-[var(--haip-band-fg)]"><Moon size={16} className="mt-0.5 shrink-0" />Between {settingsQ.data.quiet_hours.start} and {settingsQ.data.quiet_hours.end} this alert waits until morning, so nobody is woken up.</p>
            )}
            <p className="text-[13px] text-[var(--haip-fg-subtle)]">Tapping "Can't take it" on WhatsApp moves the alert to the next person at once. Names show who would hear about a {dutyWord} problem right now.</p>
          </div>

          {form && (
            <Card className="p-0">
              <CardHeader title="Time to answer" description="Same for every duty. After this, the next person is alerted." />
              <CardBody className="flex flex-col gap-3 px-4 py-4">
                <form className="flex flex-col gap-3" onSubmit={e => { e.preventDefault(); saveSettings.mutate(form); }}>
                  {SEVERITIES.map(k => (
                    <label key={k} className="flex min-h-12 items-center justify-between gap-3 text-[15px] font-semibold">
                      {SEVERITY_LABELS[k]}
                      <span className="flex items-center gap-2 text-[14px] font-medium text-[var(--haip-fg-subtle)]">
                        <input type="number" min={1} max={1440} required inputMode="numeric" value={form.ack[k]} aria-label={`${SEVERITY_LABELS[k]}: minutes to answer`}
                          onChange={e => setForm({ ...form, ack: { ...form.ack, [k]: e.target.value } })}
                          className="num min-h-11 w-20 rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)] px-2 text-right text-[16px] text-[var(--haip-fg)]" />min
                      </span>
                    </label>
                  ))}
                  <fieldset className="flex flex-col gap-2 border-t border-[var(--haip-border)] pt-3">
                    <legend className="text-[15px] font-semibold">Quiet hours</legend>
                    <p className="text-[13px] text-[var(--haip-fg-subtle)]">Normal and low alerts wait. High and critical always go out.</p>
                    <div className="grid grid-cols-2 gap-2">
                      <label className={label}>From<input className={input} type="time" required value={form.start} onChange={e => setForm({ ...form, start: e.target.value })} /></label>
                      <label className={label}>To<input className={input} type="time" required value={form.end} onChange={e => setForm({ ...form, end: e.target.value })} /></label>
                    </div>
                  </fieldset>
                  <button type="submit" disabled={saveSettings.isPending} className="haip-btn-primary min-h-12">{saveSettings.isPending ? "Saving…" : "Save times"}</button>
                </form>
              </CardBody>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}
