"use client";
// Settings > AI learning (owner changes it, a manager can see it). Per area: watch | suggest | act; the master kill switch;
// whether tests may start by themselves; the Build Your Own driving limit; experiment defaults. Backend: GET/PUT
// /ai/learning-settings (audited `learning.settings_changed`). Prices, policies and discount RULES are never changed
// automatically: those areas stop at "suggest".
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Loader2 } from "@/lib/icons";
import { useToast } from "@/components/ui/toast";
import { Card, CardBody, CardHeader, PageHeader, StatusPill } from "@/components/ui/kit";

type Level = "watch" | "suggest" | "act";
interface Settings {
  paused: boolean; experiments_allowed: boolean; areas: Record<string, Level>; byo_max_drive_hours_per_day: number;
  peak_dates: { start: string; end: string }[]; max_lessons_in_prompt: number;
  experiments: { min_sample_per_arm: number; max_days: number; stop_loss_relative: number; stop_loss_p: number; keep_p: number };
}
interface View { settings: Settings; areas: { key: string; default: Level; max: Level }[] }

const AREA_TEXT: Record<string, { title: string; desc: string }> = {
  replies: { title: "Replies and wording", desc: "Opening line, question order, follow-up style and timing. Tested first, kept only if better." },
  prices: { title: "Prices", desc: "Published prices only; a discount only within your published discount policy, never on peak dates." },
  routes: { title: "Routes and packages", desc: "Published routes; Build Your Own only within the driving limit and with a free vehicle." },
  holds_payments: { title: "Holding dates, payment links", desc: "A manager taps once to send." },
  policy_rules: { title: "Changing a price, policy or discount rule", desc: "Always a suggestion for the owner. Never automatic." },
  ads_budget: { title: "Ads budget", desc: "Suggestions only; Marketing Studio's caps still apply." },
};
const LEVELS: { id: Level; label: string }[] = [{ id: "watch", label: "Watch" }, { id: "suggest", label: "Suggest" }, { id: "act", label: "Act within limits" }];
const num = "w-24 rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-2.5 py-2 text-[16px] text-[var(--haip-fg)] sm:text-sm";

function Toggle({ label, hint, checked, disabled, onChange }: { label: string; hint: string; checked: boolean; disabled: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex min-h-[44px] items-center justify-between gap-4 border-t border-[var(--haip-border)] py-3 first:border-t-0">
      <span><span className="block text-sm font-semibold text-[var(--haip-fg)]">{label}</span><span className="block text-xs text-[var(--haip-fg-subtle)]">{hint}</span></span>
      <input type="checkbox" className="h-5 w-5 accent-[var(--primary)]" checked={checked} disabled={disabled} onChange={e => onChange(e.target.checked)} />
    </label>
  );
}

export default function LearningSettingsPage() {
  const { data: session } = useSession();
  const role = session?.user?.role;
  const canView = role === "owner" || role === "manager";
  const canEdit = role === "owner";
  const qc = useQueryClient();
  const { toast } = useToast();
  const { data, isPending, isError } = useQuery<View>({ queryKey: ["learning-settings"], queryFn: () => api.get("/ai/learning-settings").then(r => r.data), enabled: canView });
  const [cfg, setCfg] = useState<Settings | null>(null);
  useEffect(() => { if (data) setCfg(data.settings); }, [data]);
  const save = useMutation({
    mutationFn: () => api.put("/ai/learning-settings", cfg).then(r => r.data),
    onSuccess: (fresh: View) => { qc.setQueryData(["learning-settings"], fresh); qc.invalidateQueries({ queryKey: ["learning-board"] }); toast({ variant: "success", title: "Saved" }); },
    onError: (e: unknown) => {
      const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      toast({ variant: "error", title: "Couldn't save", description: typeof d === "string" ? d : "Check the values and try again." });
    },
  });
  if (!canView) return <div className="p-8 text-sm text-[var(--haip-fg-muted)]">Only an owner or manager can see these settings.</div>;
  if (isPending || !cfg || !data) {
    return <div className="flex items-center gap-2 p-8 text-sm text-[var(--haip-fg-muted)]">{isError ? "Couldn't load the settings. Refresh to try again." : <><Loader2 size={16} className="animate-spin" /> Loading…</>}</div>;
  }
  const set = (p: Partial<Settings>) => setCfg(c => (c ? { ...c, ...p } : c));
  const setExp = (p: Partial<Settings["experiments"]>) => setCfg(c => (c ? { ...c, experiments: { ...c.experiments, ...p } } : c));
  const order = ["watch", "suggest", "act"];

  return (
    <div className="h-full overflow-y-auto bg-[var(--haip-bg,var(--background))]">
      <div className="mx-auto max-w-3xl space-y-5 px-4 py-6 sm:px-6">
        <PageHeader title="AI learning" subtitle="How far HAIP may change the way the AI sells, from what the analyst finds. Every change is tested on half of new conversations first and can be undone." />
        <Card>
          <CardHeader title="Master switch" description={canEdit ? "Pause stops every test at once." : "Only the owner can change these settings."} />
          <CardBody>
            <Toggle label="Pause all learning" hint="Every conversation uses your normal settings immediately." checked={cfg.paused} disabled={!canEdit} onChange={v => set({ paused: v })} />
            <Toggle label="Tests may start by themselves" hint="Off: every change waits for your tap, even in areas set to act." checked={cfg.experiments_allowed} disabled={!canEdit} onChange={v => set({ experiments_allowed: v })} />
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="What the AI may decide" description="Watch = report only. Suggest = you approve with one tap. Act = within the limits shown." />
          <CardBody className="space-y-4">
            {data.areas.map(a => (
              <div key={a.key} className="border-t border-[var(--haip-border)] pt-3 first:border-t-0 first:pt-0">
                <p className="text-sm font-semibold text-[var(--haip-fg)]">{AREA_TEXT[a.key]?.title ?? a.key} {cfg.areas[a.key] === a.default && <StatusPill tone="neutral">Default</StatusPill>}</p>
                <p className="mb-2 text-xs text-[var(--haip-fg-subtle)]">{AREA_TEXT[a.key]?.desc}</p>
                <div className="flex flex-wrap gap-2" role="radiogroup" aria-label={AREA_TEXT[a.key]?.title ?? a.key}>
                  {LEVELS.filter(l => order.indexOf(l.id) <= order.indexOf(a.max)).map(l => (
                    <button key={l.id} type="button" role="radio" aria-checked={cfg.areas[a.key] === l.id} disabled={!canEdit}
                      onClick={() => set({ areas: { ...cfg.areas, [a.key]: l.id } })}
                      className={cn("min-h-[44px] rounded-full border px-4 text-sm font-semibold disabled:cursor-default",
                        cfg.areas[a.key] === l.id ? "border-primary bg-[var(--haip-primary-tint)] text-primary" : "border-[var(--haip-border)] text-[var(--haip-fg-muted)]")}>
                      {l.label}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="Limits and test rules" />
          <CardBody className="space-y-3 text-sm">
            {([
              ["Build Your Own: most driving hours a day", cfg.byo_max_drive_hours_per_day, 2, 14, 0.5, (v: number) => set({ byo_max_drive_hours_per_day: v })],
              ["Conversations per side before deciding", cfg.experiments.min_sample_per_arm, 10, 2000, 1, (v: number) => setExp({ min_sample_per_arm: v })],
              ["Longest a test runs (days)", cfg.experiments.max_days, 3, 60, 1, (v: number) => setExp({ max_days: v })],
              ["Roll back when worse by (share, 0.3 = 30%)", cfg.experiments.stop_loss_relative, 0.05, 0.9, 0.05, (v: number) => setExp({ stop_loss_relative: v })],
              ["Proven lessons shown to the AI", cfg.max_lessons_in_prompt, 0, 10, 1, (v: number) => set({ max_lessons_in_prompt: v })],
            ] as [string, number, number, number, number, (v: number) => void][]).map(([label, value, min, max, step, on]) => (
              <label key={label} className="flex items-center justify-between gap-4">
                <span className="text-[var(--haip-fg)]">{label}</span>
                <input type="number" className={num} value={value} min={min} max={max} step={step} disabled={!canEdit} onChange={e => on(Number(e.target.value))} />
              </label>
            ))}
            <p className="text-xs text-[var(--haip-fg-subtle)]">Peak dates with no discount: {cfg.peak_dates.map(p => `${p.start} to ${p.end}`).join(", ") || "none"}. A change is kept only when it is better with p &lt; {cfg.experiments.keep_p}.</p>
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
