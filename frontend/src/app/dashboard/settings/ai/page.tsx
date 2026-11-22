"use client";
// Settings > AI (docs/ai/AI_SWITCHES_SPEC.md step 3): where the workspace uses AI, one line per feature with its switch and
// its last-30-day cost. The ONLY place to change the WhatsApp / Instagram reply modes. Backend: GET/PATCH /settings/ai
// (owner, manager; every change audited). Each change saves at once.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Loader2 } from "@/lib/icons";
import { useToast } from "@/components/ui/toast";
import { Card, CardBody, CardHeader, PageHeader, StatusPill } from "@/components/ui/kit";
import {
  type AiSettingsView, type FeatureRow, type Mode, type ReplyRow,
  MODE_LABELS, ROW_TEXT, THRESHOLDS, costLine, rupees,
} from "@/components/settings/aiSwitches";

const KEY = ["settings-ai"];

type Patch = { features?: Record<string, boolean>; reply_modes?: Record<string, Mode>; thresholds?: Record<string, number> };

function ReplyLine({ row, rate, disabled, onChange }: {
  row: ReplyRow; rate: number; disabled: boolean; onChange: (p: Patch) => void;
}) {
  const text = ROW_TEXT[row.key] ?? { title: row.key, does: "" };
  return (
    <div className="border-t border-[var(--haip-border)] py-4 first:border-t-0 first:pt-0">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <p className="text-sm font-semibold text-[var(--haip-fg)]">{text.title}</p>
        <p className="text-xs text-[var(--haip-fg-muted)]">{costLine(row, rate)}</p>
      </div>
      <p className="mt-0.5 text-xs text-[var(--haip-fg-subtle)]">{text.does}</p>
      <div className="mt-2 grid grid-cols-3 gap-1.5" role="radiogroup" aria-label={`${text.title} mode`}>
        {row.choices.map(m => {
          const on = row.mode === m;
          return (
            <button key={m} type="button" role="radio" aria-checked={on} disabled={disabled}
              onClick={() => !on && onChange({ reply_modes: { [row.key]: m } })}
              className={cn("min-h-[44px] rounded-xl border px-2 text-[13px] font-semibold transition-colors disabled:opacity-60",
                on ? "border-primary bg-[var(--haip-primary-tint)] text-[var(--haip-fg)]"
                  : "border-[var(--haip-border)] text-[var(--haip-fg-muted)] hover:bg-[var(--haip-surface)]")}>
              {MODE_LABELS[m]}
            </button>
          );
        })}
      </div>
      {row.mode === "autonomous" && (
        row.threshold_editable ? (
          <label className="mt-2 flex items-center justify-between gap-3 text-xs text-[var(--haip-fg-muted)]">
            Send only when the AI is at least this sure; below it, the reply waits as a draft.
            <select value={String(row.threshold)} disabled={disabled}
              onChange={e => onChange({ thresholds: { [row.key]: Number(e.target.value) } })}
              className="min-h-[44px] rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-2 text-[16px] text-[var(--haip-fg)] sm:text-sm">
              {[...new Set([...THRESHOLDS, row.threshold])].sort().map(t => (
                <option key={t} value={String(t)}>{Math.round(t * 100)}%</option>
              ))}
            </select>
          </label>
        ) : (
          <p className="mt-2 text-xs text-[var(--haip-fg-subtle)]">Uses the Instagram DM confidence ({Math.round(row.threshold * 100)}%).</p>
        )
      )}
      {row.unused_drafts > 0 && row.mode === "shadow" && (
        <p className="mt-2 text-xs text-[var(--haip-status-warning-fg)]">
          {row.unused_drafts} {row.unused_drafts === 1 ? "draft" : "drafts"} nobody used in the last 30 days.
        </p>
      )}
    </div>
  );
}

function FeatureLine({ row, rate, disabled, onChange }: {
  row: FeatureRow; rate: number; disabled: boolean; onChange: (p: Patch) => void;
}) {
  const text = ROW_TEXT[row.key] ?? { title: row.key, does: "" };
  return (
    <label className="flex min-h-[44px] items-center justify-between gap-4 border-t border-[var(--haip-border)] py-3 first:border-t-0 first:pt-0">
      <span className="min-w-0">
        <span className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
          <span className="text-sm font-semibold text-[var(--haip-fg)]">{text.title}</span>
          <span className="text-xs text-[var(--haip-fg-muted)]">{costLine(row, rate)}</span>
        </span>
        <span className="block text-xs text-[var(--haip-fg-subtle)]">{text.does}</span>
      </span>
      <input type="checkbox" role="switch" aria-label={text.title} className="h-5 w-5 shrink-0 accent-[var(--primary)]"
        checked={row.enabled} disabled={disabled} onChange={e => onChange({ features: { [row.key]: e.target.checked } })} />
    </label>
  );
}

export default function AiSettingsPage() {
  const { data: session } = useSession();
  const role = session?.user?.role;
  const canView = role === "owner" || role === "manager";
  const qc = useQueryClient();
  const { toast } = useToast();

  const { data, isPending, isError } = useQuery<AiSettingsView>({
    queryKey: KEY,
    queryFn: () => api.get("/settings/ai").then(r => r.data),
    enabled: canView,
  });

  const save = useMutation({
    mutationFn: (patch: Patch) => api.patch("/settings/ai", patch).then(r => r.data),
    onSuccess: (fresh: AiSettingsView) => {
      qc.setQueryData(KEY, fresh);
      toast({ variant: "success", title: "Saved", description: "AI settings take effect within a minute." });
    },
    onError: (e: unknown) => {
      const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      toast({ variant: "error", title: "Couldn't save", description: typeof detail === "string" ? detail : "Try again." });
    },
  });

  if (!canView) {
    return <div className="p-8 text-sm text-[var(--haip-fg-muted)]">Only an owner or manager can see the AI settings.</div>;
  }
  if (isPending || !data) {
    return (
      <div className="flex items-center gap-2 p-8 text-sm text-[var(--haip-fg-muted)]">
        {isError ? "Couldn't load the AI settings. Refresh to try again." : <><Loader2 size={16} className="animate-spin" /> Loading…</>}
      </div>
    );
  }
  const rate = data.usd_inr;
  const busy = save.isPending;

  return (
    <div className="h-full overflow-y-auto bg-[var(--haip-bg,var(--background))]">
      <div className="mx-auto max-w-3xl space-y-5 px-4 py-6 sm:px-6">
        <PageHeader title="AI" subtitle="Choose where HAIP uses AI. Anything switched off makes no AI call and costs nothing." />

        <Card className="flex flex-wrap items-baseline justify-between gap-2 p-4">
          <span className="text-sm text-[var(--haip-fg-muted)]">AI cost, last {data.period_days} days</span>
          <span className="font-[family-name:var(--font-display)] text-2xl font-semibold text-[var(--haip-fg)]">
            {rupees(data.total_cost_usd, rate)}
          </span>
        </Card>

        <Card>
          <CardHeader title="Replies to guests"
            description="Off: no AI reply. Draft for staff: the AI writes, a person sends. Reply automatically: the AI sends when it is sure enough." />
          <CardBody>
            {data.reply_modes.map(r => <ReplyLine key={r.key} row={r} rate={rate} disabled={busy} onChange={p => save.mutate(p)} />)}
            <p className="mt-3 border-t border-[var(--haip-border)] pt-3 text-xs text-[var(--haip-fg-subtle)]">
              Write a draft button and rewrites: {costLine(data.replies_other, rate)}. Personal WhatsApp and lead forms never get
              AI replies: HAIP can only read them.
            </p>
            <p className="mt-2 text-xs text-[var(--haip-fg-subtle)]">
              Before choosing Reply automatically, add your FAQs and policies to the{" "}
              <a href="/dashboard/settings/knowledge" className="font-semibold text-primary underline">knowledge base</a>{" "}
              and read a few weeks of drafts.
            </p>
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Other AI work" description="Switch any of these off; what is already written stays." />
          <CardBody>
            {data.features.map(f => <FeatureLine key={f.key} row={f} rate={rate} disabled={busy} onChange={p => save.mutate(p)} />)}
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Switched with their module" description="These follow their own module in Settings; shown here for cost." />
          <CardBody>
            {data.module_switched.map(m => {
              const text = ROW_TEXT[m.key] ?? { title: m.key, does: "" };
              return (
                <div key={m.key} className="flex flex-wrap items-baseline justify-between gap-x-4 border-t border-[var(--haip-border)] py-2.5 first:border-t-0 first:pt-0">
                  <span className="min-w-0">
                    <span className="block text-sm font-semibold text-[var(--haip-fg)]">{text.title}</span>
                    <span className="block text-xs text-[var(--haip-fg-subtle)]">{text.does}</span>
                  </span>
                  <span className="text-xs text-[var(--haip-fg-muted)]">{costLine(m, rate)}</span>
                </div>
              );
            })}
          </CardBody>
        </Card>

        <p className="text-xs text-[var(--haip-fg-subtle)]">
          <StatusPill tone="neutral">Note</StatusPill>{" "}
          AI providers bill in US dollars; rupees are shown at ₹{rate} per dollar. Every change here is recorded in the audit log.
        </p>
      </div>
    </div>
  );
}
