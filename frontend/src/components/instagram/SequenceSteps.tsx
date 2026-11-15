"use client";
// Follow-up messages after an automation's final message (services/ig_sequence.py): up to 3, each after a wait.
import { Plus, Trash2 } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { SEQUENCE_WAITS, SEQUENCE_WINDOW_MINUTES, type IgSequenceStep } from "./automationTypes";

const field = "min-h-11 w-full rounded-[12px] border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-[16px] sm:text-[14.5px] text-[var(--haip-fg)] placeholder:text-[var(--haip-fg-subtle)] focus:border-primary focus:outline-none";

export const sequenceTotal = (steps: IgSequenceStep[]) => steps.reduce((n, s) => n + (s.after_minutes || 0), 0);

export function SequenceSteps({ value, onChange }: { value: IgSequenceStep[]; onChange: (v: IgSequenceStep[]) => void }) {
  const set = (i: number, patch: Partial<IgSequenceStep>) => onChange(value.map((s, j) => (j === i ? { ...s, ...patch } : s)));
  const total = sequenceTotal(value);
  const over = total > SEQUENCE_WINDOW_MINUTES;
  return (
    <div className="grid gap-3">
      <ol className="grid gap-3">
        {value.map((s, i) => (
          <li key={i} className="rounded-[14px] border border-[var(--haip-border)] p-3">
            <div className="flex items-center gap-2">
              <span className="shrink-0 text-[13.5px] font-medium text-[var(--haip-fg-muted)]">{i === 0 ? "After the final message, wait" : "Then wait"}</span>
              <select className={field} value={s.after_minutes} onChange={e => set(i, { after_minutes: Number(e.target.value) })} aria-label={`Wait before follow-up ${i + 1}`}>
                {SEQUENCE_WAITS.map(w => <option key={w.value} value={w.value}>{w.label}</option>)}
              </select>
              <button type="button" aria-label={`Remove follow-up ${i + 1}`} onClick={() => onChange(value.filter((_, j) => j !== i))}
                className="flex size-11 shrink-0 items-center justify-center rounded-full border border-[var(--haip-border)]"><Trash2 size={15} /></button>
            </div>
            <textarea className={cn(field, "mt-2 min-h-[72px] py-2.5 leading-relaxed")} value={s.text} maxLength={640}
              onChange={e => set(i, { text: e.target.value })} placeholder="Did you get a chance to look, {first_name}?" aria-label={`Follow-up ${i + 1} text`} />
            <label className="mt-2 flex min-h-11 cursor-pointer items-center gap-3 text-[14px]">
              <input type="checkbox" className="size-5 accent-[var(--primary)]" checked={!!s.button}
                onChange={e => set(i, { button: e.target.checked ? { title: "See details", url: "" } : null })} />
              Add a link button
            </label>
            {s.button && (
              <div className="grid gap-2 sm:grid-cols-[160px_1fr]">
                <input className={field} value={s.button.title} maxLength={20} aria-label={`Follow-up ${i + 1} button text`}
                  onChange={e => set(i, { button: { ...s.button!, title: e.target.value } })} />
                <input className={field} value={s.button.url} inputMode="url" placeholder="https://…" aria-label={`Follow-up ${i + 1} button link`}
                  onChange={e => set(i, { button: { ...s.button!, url: e.target.value } })} />
              </div>
            )}
          </li>
        ))}
      </ol>
      {value.length < 3 && (
        <button type="button" onClick={() => onChange([...value, { text: "", after_minutes: value.length ? 180 : 60 }])}
          className="inline-flex min-h-11 items-center gap-1.5 self-start text-[14px] font-medium text-primary"><Plus size={15} /> Add a follow-up</button>
      )}
      {value.length > 0 && (
        <p className={cn("text-[13px]", over ? "text-[var(--haip-status-danger-fg)]" : "text-[var(--haip-fg-subtle)]")}>
          {over
            ? "These add up to more than 23 hours. Instagram stops allowing messages 24 hours after the person's last message."
            : "Each one is sent only if nobody has written since: a reply from the guest, your team or the AI stops the rest."}
        </p>
      )}
    </div>
  );
}
