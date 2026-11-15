"use client";
// The question list of an Instagram DM form (services/ig_dm_form.py): asked one at a time after the tap.
import { useState } from "react";
import { ChevronDown, ChevronUp, Plus, Trash2, X } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { FORM_KEYS, type IgFormKey, type IgFormQuestion } from "./automationTypes";

const field = "min-h-11 w-full rounded-[12px] border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-[16px] sm:text-[14.5px] text-[var(--haip-fg)] placeholder:text-[var(--haip-fg-subtle)] focus:border-primary focus:outline-none";
const iconBtn = "flex size-11 shrink-0 items-center justify-center rounded-full border border-[var(--haip-border)] disabled:opacity-40";

const STARTER: Record<IgFormKey, string> = {
  dates: "When are you planning to come?",
  guests: "How many guests?",
  phone: "Your WhatsApp number, so our team can send the details.",
  email: "Your email, so we can send the brochure.",
  budget: "What budget do you have in mind?",
  occasion: "Is it for a special occasion?",
  custom: "",
};

function Options({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const o = draft.trim().slice(0, 20);
    if (o && !value.includes(o) && value.length < 10) onChange([...value, o]);
    setDraft("");
  };
  return (
    <div>
      <div className="flex flex-wrap gap-1.5">
        {value.map(o => (
          <span key={o} className="inline-flex items-center gap-1 rounded-full border border-[var(--haip-border)] py-1 pl-3 pr-1 text-[13px]">
            {o}
            <button type="button" aria-label={`Remove option ${o}`} onClick={() => onChange(value.filter(x => x !== o))} className="flex size-7 items-center justify-center rounded-full"><X size={12} /></button>
          </span>
        ))}
      </div>
      <input className={cn(field, "mt-2")} value={draft} maxLength={20} placeholder="Add a tap option (optional), then Enter"
        onChange={e => setDraft(e.target.value)} onBlur={add}
        onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); add(); } }} aria-label="Add a tap option" />
    </div>
  );
}

export function FormQuestions({ value, onChange }: { value: IgFormQuestion[]; onChange: (v: IgFormQuestion[]) => void }) {
  const set = (i: number, patch: Partial<IgFormQuestion>) => onChange(value.map((q, j) => (j === i ? { ...q, ...patch } : q)));
  const move = (i: number, d: -1 | 1) => {
    const next = [...value];
    [next[i], next[i + d]] = [next[i + d], next[i]];
    onChange(next);
  };
  const used = new Set(value.filter(q => q.key !== "custom").map(q => q.key));
  return (
    <div className="grid gap-3">
      <ol className="grid gap-3">
        {value.map((q, i) => (
          <li key={i} className="rounded-[14px] border border-[var(--haip-border)] p-3">
            <div className="flex items-center gap-2">
              <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-[var(--haip-primary-tint)] text-[12.5px] font-semibold text-primary">{i + 1}</span>
              <select className={field} value={q.key} aria-label={`Question ${i + 1} type`}
                onChange={e => { const key = e.target.value as IgFormKey; set(i, { key, text: q.text || STARTER[key] }); }}>
                {FORM_KEYS.map(k => <option key={k.value} value={k.value} disabled={k.value !== q.key && k.value !== "custom" && used.has(k.value)}>{k.label}</option>)}
              </select>
              <button type="button" className={iconBtn} aria-label="Move up" disabled={i === 0} onClick={() => move(i, -1)}><ChevronUp size={16} /></button>
              <button type="button" className={iconBtn} aria-label="Move down" disabled={i === value.length - 1} onClick={() => move(i, 1)}><ChevronDown size={16} /></button>
              <button type="button" className={iconBtn} aria-label="Remove question" disabled={q.key === "phone"} onClick={() => onChange(value.filter((_, j) => j !== i))}><Trash2 size={15} /></button>
            </div>
            <input className={cn(field, "mt-2")} value={q.text} maxLength={300} onChange={e => set(i, { text: e.target.value })}
              placeholder="What HAIP asks" aria-label={`Question ${i + 1} text`} />
            {q.key === "phone"
              ? <p className="mt-2 text-[13px] text-[var(--haip-fg-subtle)]">Required. HAIP checks the number and asks once more if it doesn&apos;t look right. Skipped for people HAIP already has a number for.</p>
              : <div className="mt-2"><Options value={q.options ?? []} onChange={options => set(i, { options })} /></div>}
          </li>
        ))}
      </ol>
      {value.length < 6 && (
        <button type="button" onClick={() => onChange([...value, { key: "custom", text: "", options: [] }])}
          className="inline-flex min-h-11 items-center gap-1.5 self-start text-[14px] font-medium text-primary"><Plus size={15} /> Add a question</button>
      )}
    </div>
  );
}
