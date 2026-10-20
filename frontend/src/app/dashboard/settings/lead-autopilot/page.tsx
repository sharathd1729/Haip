"use client";
// Settings > Lead autopilot. How far Leads360 may move lead stages by itself, from calls, chats, bookings and timing.
// Backend: GET/PUT /lead-autopilot/settings (lead_autopilot_service). Owner changes it (audited); a manager can see it.
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Loader2 } from "@/lib/icons";
import { useToast } from "@/components/ui/toast";
import { Card, CardBody, CardHeader, PageHeader, StatusPill } from "@/components/ui/kit";

type Mode = "off" | "suggest" | "autopilot";
interface Settings {
  mode: Mode;
  ai_threshold: number;
  ai_enabled: boolean;
  silence_days: number;
  quote_silence_days: number;
  unanswered_calls: number;
  applied_30d: number;
  undone_30d: number;
  suggested_open: number;
}
type Config = Omit<Settings, "applied_30d" | "undone_30d" | "suggested_open">;

const MODES: { id: Mode; title: string; desc: string }[] = [
  { id: "suggest", title: "Suggest only", desc: "The autopilot suggests a stage on the lead page; a person clicks Apply. Nothing moves by itself." },
  { id: "autopilot", title: "Autopilot", desc: "Clear cases move by themselves (booking → Sold, dates passed, explicit decline, unanswered calls, no reply). AI reads move only above the confidence below. Every move can be undone." },
  { id: "off", title: "Off", desc: "No automatic moves and no suggestions." },
];

const RULES = [
  "A booking linked to the lead → Sold",
  "Travel date passed with no booking → Lost (dates)",
  "Guest declined (call marked lost, or “not interested / booked elsewhere / cancelled the trip”) → Lost",
  "Unanswered calls in a row over 2+ days → RNR",
  "Quote sent, no reply → Lost (no response)",
  "We followed up, no reply → Lost (no response)",
  "Phone + dates, route or group size → Active",
];

const fieldCls = "w-20 rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-2.5 py-2 text-[16px] text-[var(--haip-fg)] outline-none focus-visible:ring-2 focus-visible:ring-primary sm:text-sm";

function NumberRow({ label, hint, value, min, max, step = 1, disabled, onChange }: {
  label: string; hint: string; value: number; min: number; max: number; step?: number; disabled: boolean; onChange: (v: number) => void;
}) {
  return (
    <label className="flex items-center justify-between gap-4 border-t border-[var(--haip-border)] py-3">
      <span className="min-w-0">
        <span className="block text-sm font-semibold text-[var(--haip-fg)]">{label}</span>
        <span className="block text-xs text-[var(--haip-fg-subtle)]">{hint}</span>
      </span>
      <input type="number" className={fieldCls} value={value} min={min} max={max} step={step} disabled={disabled}
        onChange={e => onChange(Number(e.target.value))} />
    </label>
  );
}

export default function LeadAutopilotPage() {
  const { data: session } = useSession();
  const role = session?.user?.role;
  const canView = role === "owner" || role === "manager";
  const canEdit = role === "owner";
  const qc = useQueryClient();
  const { toast } = useToast();

  const { data, isPending, isError } = useQuery<Settings>({
    queryKey: ["lead-autopilot-settings"],
    queryFn: () => api.get("/lead-autopilot/settings").then(r => r.data),
    enabled: canView,
  });
  const [cfg, setCfg] = useState<Config | null>(null);
  useEffect(() => {
    if (!data) return;
    const { applied_30d: _a, undone_30d: _u, suggested_open: _s, ...rest } = data;
    setCfg(rest);
  }, [data]);

  const save = useMutation({
    mutationFn: () => api.put("/lead-autopilot/settings", cfg).then(r => r.data),
    onSuccess: (fresh: Settings) => {
      qc.setQueryData(["lead-autopilot-settings"], fresh);
      toast({ variant: "success", title: "Lead autopilot saved", description: fresh.mode === "autopilot" ? "Clear cases now move by themselves." : "Saved." });
    },
    onError: (e: unknown) => {
      const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      toast({ variant: "error", title: "Couldn't save", description: typeof detail === "string" ? detail : "Check the values and try again." });
    },
  });

  if (!canView) {
    return <div className="p-8 text-sm text-[var(--haip-fg-muted)]">Only an owner or manager can see the lead autopilot settings.</div>;
  }
  if (isPending || !cfg || !data) {
    return (
      <div className="flex items-center gap-2 p-8 text-sm text-[var(--haip-fg-muted)]">
        {isError ? "Couldn't load the lead autopilot settings. Refresh to try again." : <><Loader2 size={16} className="animate-spin" /> Loading…</>}
      </div>
    );
  }
  const set = (patch: Partial<Config>) => setCfg(c => (c ? { ...c, ...patch } : c));

  return (
    <div className="h-full overflow-y-auto bg-[var(--haip-bg,var(--background))]">
      <div className="mx-auto max-w-3xl space-y-5 px-4 py-6 sm:px-6">
        <PageHeader title="Lead autopilot"
          subtitle="Keep Leads360 stages in step with what actually happened on calls, chats and bookings." />

        <div className="grid grid-cols-3 gap-2">
          {[["Moved, last 30 days", data.applied_30d], ["Undone, last 30 days", data.undone_30d], ["Open suggestions", data.suggested_open]].map(([label, n]) => (
            <Card key={label as string} className="p-3">
              <p className="text-[11px] text-[var(--haip-fg-subtle)]">{label}</p>
              <p className="font-[family-name:var(--font-display)] text-xl font-semibold text-[var(--haip-fg)]">{n}</p>
            </Card>
          ))}
        </div>

        <Card>
          <CardHeader title="Mode" description={canEdit ? "Pick one." : "Only the owner can change this."} />
          <CardBody>
            <div className="grid gap-2" role="radiogroup" aria-label="Mode">
              {MODES.map(m => {
                const on = cfg.mode === m.id;
                return (
                  <button key={m.id} type="button" role="radio" aria-checked={on} disabled={!canEdit} onClick={() => set({ mode: m.id })}
                    className={cn("min-h-[44px] rounded-xl border p-3 text-left transition-colors disabled:cursor-default",
                      on ? "border-primary bg-[var(--haip-primary-tint)]" : "border-[var(--haip-border)] hover:bg-[var(--haip-surface)]")}>
                    <span className="flex items-center gap-2 text-sm font-semibold text-[var(--haip-fg)]">
                      {m.title} {m.id === "suggest" && <StatusPill tone="neutral">Default</StatusPill>}
                    </span>
                    <span className="mt-0.5 block text-xs text-[var(--haip-fg-subtle)]">{m.desc}</span>
                  </button>
                );
              })}
            </div>
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Rules and limits" description="Rules run first. The AI only reads leads no rule decides, and must quote the message or call it relies on." />
          <CardBody>
            <ul className="mb-3 list-disc space-y-1 pl-5 text-[13px] text-[var(--haip-fg-muted)]">
              {RULES.map(r => <li key={r}>{r}</li>)}
            </ul>
            <p className="mb-3 text-xs text-[var(--haip-fg-subtle)]">
              Always: a pinned lead is left alone, nothing leaves Sold, nothing moves backwards, and a lead is never auto-Lost
              while a payment link is open or a quote is still valid for a future check-in.
            </p>
            <label className="flex items-center justify-between gap-4 border-t border-[var(--haip-border)] py-3">
              <span>
                <span className="block text-sm font-semibold text-[var(--haip-fg)]">AI reads ambiguous leads</span>
                <span className="block text-xs text-[var(--haip-fg-subtle)]">After a call or a burst of messages, when no rule decides.</span>
              </span>
              <input type="checkbox" className="h-5 w-5 accent-[var(--primary)]" checked={cfg.ai_enabled} disabled={!canEdit}
                onChange={e => set({ ai_enabled: e.target.checked })} />
            </label>
            <NumberRow label="AI confidence to move by itself" hint="0.5 – 1.0. Below it, the AI only suggests." value={cfg.ai_threshold}
              min={0.5} max={1} step={0.05} disabled={!canEdit} onChange={v => set({ ai_threshold: v })} />
            <NumberRow label="Unanswered calls → RNR" hint="In a row, across at least two days." value={cfg.unanswered_calls}
              min={2} max={10} disabled={!canEdit} onChange={v => set({ unanswered_calls: v })} />
            <NumberRow label="Days without reply to a quote → Lost" hint="2 – 60 days." value={cfg.quote_silence_days}
              min={2} max={60} disabled={!canEdit} onChange={v => set({ quote_silence_days: v })} />
            <NumberRow label="Days without reply after our follow-up → Lost" hint="3 – 90 days." value={cfg.silence_days}
              min={3} max={90} disabled={!canEdit} onChange={v => set({ silence_days: v })} />
          </CardBody>
        </Card>

        {canEdit && (
          <div className="flex justify-end">
            <button type="button" onClick={() => save.mutate()} disabled={save.isPending}
              className="inline-flex min-h-[44px] items-center gap-2 rounded-full bg-primary px-5 text-sm font-semibold text-primary-foreground disabled:opacity-60">
              {save.isPending && <Loader2 size={14} className="animate-spin" />} Save
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
