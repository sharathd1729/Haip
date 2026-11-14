"use client";
// Correct the AI's QA score (owner / manager / compliance). Each criterion is shown on its own scale (yes/no = 0-1,
// graded = 0-3); only what the person changes is sent, with a reason. The backend recomputes the score, keeps the AI's
// original, audits it and updates the call's score everywhere (POST /qa/scores/{id}/override).
import { useState } from "react";
import api from "@/lib/api";
import { Loader2 } from "@/lib/icons";
import { useToast } from "@/components/ui/toast";

export interface CorrectableCriterion { id?: string; criterion: string; name?: string | null; method?: string | null; score: number; max_score: number }

export function CorrectScore({ scoreId, criteria, onDone }: { scoreId: string; criteria: CorrectableCriterion[]; onDone: () => void }) {
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [values, setValues] = useState<Record<string, number>>({});
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const rows = criteria.filter(c => c.id || c.criterion);
  const changed = Object.entries(values).filter(([cid, v]) => rows.find(c => (c.id ?? c.criterion) === cid)?.score !== v);

  const save = async () => {
    setSaving(true);
    try {
      await api.post(`/qa/scores/${scoreId}/override`, {
        criterion_scores: changed.map(([id, score]) => ({ id, score })),
        reason: reason.trim(),
      });
      toast({ variant: "success", title: "Score corrected", description: "Dashboards and scorecards now use your score." });
      setOpen(false); setValues({}); setReason("");
      onDone();
    } catch (e) {
      const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      toast({ variant: "error", title: "Couldn't correct the score", description: typeof d === "string" ? d : "Try again." });
    } finally {
      setSaving(false);
    }
  };

  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)}
        className="mt-3 inline-flex min-h-[44px] items-center rounded-full border border-[var(--haip-border)] px-4 text-xs font-semibold text-[var(--haip-fg)]">
        Correct this score
      </button>
    );
  }
  return (
    <div className="mt-3 rounded-xl border border-[var(--haip-border)] p-3">
      <p className="text-xs font-semibold text-[var(--haip-fg)]">Correct the score</p>
      <ul className="mt-2 space-y-2">
        {rows.map(c => {
          const cid = c.id ?? c.criterion;
          const max = c.method === "ZERO_THREE" ? 3 : c.method ? 1 : c.max_score;
          const v = values[cid] ?? c.score;
          return (
            <li key={cid} className="flex items-center justify-between gap-3">
              <span className="min-w-0 truncate text-xs capitalize text-[var(--haip-fg-2)]">{(c.name ?? c.criterion).replace(/_/g, " ")}</span>
              <select aria-label={`Score for ${c.name ?? c.criterion}`} value={v}
                onChange={e => setValues(s => ({ ...s, [cid]: Number(e.target.value) }))}
                className="min-h-[36px] rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-2 text-[16px] text-[var(--haip-fg)] sm:text-xs">
                {Array.from({ length: max + 1 }, (_, i) => (
                  <option key={i} value={i}>{max === 1 ? (i ? "Yes" : "No") : `${i} / ${max}`}</option>
                ))}
              </select>
            </li>
          );
        })}
      </ul>
      <label className="mt-3 block text-xs font-medium text-[var(--haip-fg)]">Why
        <input value={reason} onChange={e => setReason(e.target.value)} maxLength={500} placeholder="What the AI got wrong"
          className="mt-1 min-h-[40px] w-full rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-2 text-[16px] text-[var(--haip-fg)] sm:text-xs" />
      </label>
      <div className="mt-3 flex gap-2">
        <button type="button" onClick={save} disabled={saving || changed.length === 0 || reason.trim().length < 3}
          className="inline-flex min-h-[40px] items-center gap-1.5 rounded-full bg-primary px-4 text-xs font-semibold text-primary-foreground disabled:opacity-50">
          {saving && <Loader2 size={12} className="animate-spin" />} Save correction
        </button>
        <button type="button" onClick={() => { setOpen(false); setValues({}); }} disabled={saving}
          className="min-h-[40px] rounded-full border border-[var(--haip-border)] px-4 text-xs font-medium text-[var(--haip-fg)]">Cancel</button>
      </div>
    </div>
  );
}
