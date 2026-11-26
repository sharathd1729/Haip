"use client";
// The settings of the selected block. Every change applies straight away (the toolbar's Save stores the flow).
// Limits come from WhatsApp (flowModel.LIMITS); inputs are 16px on phones so iOS does not zoom.
import { useState, type ReactNode } from "react";
import { Plus, Trash2, X } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { DELAY_UNITS, splitDelay } from "../flowOrder";
import {
  ACTION_LABELS, CONDITION_OPTIONS, LIMITS, SAVE_AS_OPTIONS, TRIGGER_OPTIONS, actionOf, triggerOf, uid,
  type ActionKey, type NodeData, type Option, type TriggerKind,
} from "./flowModel";
import { MediaUpload } from "./MediaUpload";
import { TemplatePicker } from "./TemplatePicker";

export const inputCls = "w-full rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 py-2 text-base sm:text-sm text-[var(--haip-fg)] focus:outline-none focus:ring-2 focus:ring-primary/30";

function Field({ label, hint, count, children }: { label: string; hint?: ReactNode; count?: [number, number]; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 flex items-baseline justify-between gap-2 text-xs font-semibold text-[var(--haip-fg-2)]">
        {label}
        {count && <span className={cn("font-normal tabular-nums", count[0] > count[1] ? "text-[var(--haip-status-danger-fg)]" : "text-[var(--haip-fg-subtle)]")}>{count[0]}/{count[1]}</span>}
      </span>
      {children}
      {hint && <span className="mt-1 block text-[12px] text-[var(--haip-fg-subtle)]">{hint}</span>}
    </label>
  );
}

const NAME_HINT = <>Use {"{first_name}"} for the guest&apos;s first name.</>;

function TextBox({ label, value, onChange, placeholder }: { label: string; value?: string; onChange: (v: string) => void; placeholder?: string }) {
  return (
    <Field label={label} hint={NAME_HINT}>
      <textarea rows={4} value={value ?? ""} placeholder={placeholder} onChange={e => onChange(e.target.value)} className={cn(inputCls, "resize-y")} />
    </Field>
  );
}

function KeywordChips({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const words = draft.split(",").map(w => w.trim().toLowerCase()).filter(w => w && !value.includes(w));
    if (words.length) onChange([...value, ...words]);
    setDraft("");
  };
  return (
    <div>
      <div className="flex gap-2">
        <input value={draft} onChange={e => setDraft(e.target.value)} placeholder="hi, hello" aria-label="Add keyword"
          onKeyDown={e => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add(); } }} onBlur={add} className={inputCls} />
        <button type="button" onClick={add} aria-label="Add keyword" className="flex size-11 shrink-0 items-center justify-center rounded-lg border border-[var(--haip-border)] text-primary">
          <Plus size={16} />
        </button>
      </div>
      {value.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {value.map(w => (
            <button key={w} type="button" onClick={() => onChange(value.filter(x => x !== w))} aria-label={`Remove ${w}`}
              className="inline-flex min-h-9 items-center gap-1 rounded-full border border-[color-mix(in_srgb,var(--primary)_25%,transparent)] bg-[var(--haip-primary-tint)] px-3 text-[13px] font-medium text-primary">
              {w} <X size={12} />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function OptionsEditor({ kind, value, onChange }: { kind: "buttons" | "rows"; value: Option[]; onChange: (v: Option[]) => void }) {
  const max = kind === "buttons" ? LIMITS.buttons : LIMITS.rows;
  const titleMax = kind === "buttons" ? LIMITS.buttonTitle : LIMITS.rowTitle;
  const set = (i: number, patch: Partial<Option>) => onChange(value.map((o, j) => (j === i ? { ...o, ...patch } : o)));
  return (
    <div className="space-y-2">
      <p className="text-xs font-semibold text-[var(--haip-fg-2)]">{kind === "buttons" ? `Buttons (up to ${max})` : `Rows (up to ${max})`}</p>
      {value.map((o, i) => (
        <div key={o.id} className="space-y-1.5 rounded-xl border border-[var(--haip-border)] p-2">
          <div className="flex items-center gap-2">
            <input value={o.title} maxLength={titleMax} aria-label={`Option ${i + 1} title`} onChange={e => set(i, { title: e.target.value })} className={inputCls} />
            <span className="w-11 shrink-0 text-right text-[11.5px] tabular-nums text-[var(--haip-fg-subtle)]">{o.title.length}/{titleMax}</span>
            <button type="button" aria-label={`Remove option ${i + 1}`} disabled={value.length <= 1} onClick={() => onChange(value.filter((_, j) => j !== i))}
              className="flex size-11 shrink-0 items-center justify-center rounded-lg text-[var(--haip-fg-subtle)] hover:text-[var(--haip-status-danger-fg)] disabled:opacity-30">
              <Trash2 size={15} />
            </button>
          </div>
          {kind === "rows" && (
            <input value={o.description ?? ""} maxLength={LIMITS.rowDescription} placeholder="Description (optional)" aria-label={`Option ${i + 1} description`}
              onChange={e => set(i, { description: e.target.value || undefined })} className={inputCls} />
          )}
        </div>
      ))}
      {value.length < max && (
        <button type="button" onClick={() => onChange([...value, { id: uid(kind === "buttons" ? "b" : "r"), title: `Option ${value.length + 1}` }])}
          className="flex min-h-11 w-full items-center justify-center gap-1.5 rounded-xl border border-dashed border-[var(--haip-border-strong)] text-sm font-medium text-primary">
          <Plus size={14} /> Add {kind === "buttons" ? "button" : "row"}
        </button>
      )}
      <p className="text-[12px] text-[var(--haip-fg-subtle)]">Each option gets its own connector on the block. &quot;Any other reply&quot; is optional.</p>
    </div>
  );
}

function ButtonLabel({ data, onChange }: { data: NodeData; onChange: (p: Partial<NodeData>) => void }) {
  return (
    <Field label="Button label" count={[(data.button_label ?? "").length, LIMITS.buttonLabel]}>
      <input value={data.button_label ?? ""} maxLength={LIMITS.buttonLabel} onChange={e => onChange({ button_label: e.target.value })} className={inputCls} />
    </Field>
  );
}

const num = (s: string) => (s.trim() === "" || Number.isNaN(Number(s)) ? undefined : Number(s));

export function NodeFields({ data, onChange }: { data: NodeData; onChange: (patch: Partial<NodeData>) => void }) {
  const t = data.type;
  return (
    <div className="space-y-4">
      {t !== "trigger" && (
        <Field label="Block name" hint="Only you see this, on the canvas.">
          <input value={data.label ?? ""} onChange={e => onChange({ label: e.target.value })} className={inputCls} />
        </Field>
      )}

      {t === "trigger" && (
        <>
          <Field label="Starts when">
            <select value={triggerOf(data)} onChange={e => onChange({ trigger: e.target.value as TriggerKind, content: e.target.value })} className={inputCls}>
              <option value="">Choose a trigger</option>
              {TRIGGER_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </Field>
          {triggerOf(data) === "keyword" && (
            <>
              <Field label="Keywords" hint="Press Enter or a comma after each one.">
                <KeywordChips value={data.keywords ?? []} onChange={keywords => onChange({ keywords })} />
              </Field>
              <fieldset>
                <legend className="mb-1.5 text-xs font-semibold text-[var(--haip-fg-2)]">Match</legend>
                <div className="grid grid-cols-2 gap-2">
                  {([["contains", "Message contains the word"], ["exact", "Whole message is the word"]] as const).map(([v, l]) => (
                    <label key={v} className={cn("flex min-h-11 cursor-pointer items-center rounded-xl border px-3 text-[13px]",
                      (data.match ?? "contains") === v ? "border-primary bg-[var(--haip-primary-tint)] text-primary" : "border-[var(--haip-border)] text-[var(--haip-fg-2)]")}>
                      <input type="radio" name="match" className="sr-only" checked={(data.match ?? "contains") === v} onChange={() => onChange({ match: v })} />
                      {l}
                    </label>
                  ))}
                </div>
              </fieldset>
            </>
          )}
        </>
      )}

      {t === "message" && <TextBox label="Message" value={data.content} onChange={content => onChange({ content })} placeholder="Hi {first_name}, welcome!" />}

      {t === "media" && (
        <>
          <MediaUpload data={data} onChange={onChange} />
          {data.media_kind !== "audio" && (
            <Field label="Caption (optional)"><input value={data.caption ?? ""} onChange={e => onChange({ caption: e.target.value })} className={inputCls} /></Field>
          )}
        </>
      )}

      {t === "location" && (
        <>
          <div className="grid grid-cols-2 gap-2">
            <Field label="Latitude"><input inputMode="decimal" value={data.latitude ?? ""} onChange={e => onChange({ latitude: num(e.target.value) })} className={inputCls} /></Field>
            <Field label="Longitude"><input inputMode="decimal" value={data.longitude ?? ""} onChange={e => onChange({ longitude: num(e.target.value) })} className={inputCls} /></Field>
          </div>
          <Field label="Place name"><input value={data.name ?? ""} onChange={e => onChange({ name: e.target.value })} className={inputCls} /></Field>
          <Field label="Address"><input value={data.address ?? ""} onChange={e => onChange({ address: e.target.value })} className={inputCls} /></Field>
        </>
      )}

      {(t === "buttons" || t === "list") && (
        <>
          <TextBox label="Message above the options" value={data.content} onChange={content => onChange({ content })} />
          {t === "list" && <ButtonLabel data={data} onChange={onChange} />}
          <OptionsEditor kind={t === "buttons" ? "buttons" : "rows"} value={(t === "buttons" ? data.buttons : data.rows) ?? []}
            onChange={v => onChange(t === "buttons" ? { buttons: v } : { rows: v })} />
        </>
      )}

      {t === "cta_url" && (
        <>
          <TextBox label="Message" value={data.content} onChange={content => onChange({ content })} />
          <ButtonLabel data={data} onChange={onChange} />
          <Field label="Link" hint="Must start with https://"><input type="url" value={data.url ?? ""} onChange={e => onChange({ url: e.target.value })} className={inputCls} /></Field>
        </>
      )}

      {t === "template" && <TemplatePicker data={data} onChange={onChange} inputCls={inputCls} />}

      {t === "question" && <QuestionFields data={data} onChange={onChange} />}

      {t === "condition" && (
        <Field label="Condition" hint="Connect both Yes and No, or the flow stops on the side you leave open.">
          <select value={data.condition ?? ""} onChange={e => onChange({ condition: e.target.value })} className={inputCls}>
            <option value="">Choose a condition</option>
            {CONDITION_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </Field>
      )}

      {t === "delay" && <DelayFields data={data} onChange={onChange} />}

      {t === "action" && (
        actionOf(data) === "add_label"
          ? <Field label="Label to add" hint="Added to the guest as a tag."><input value={data.tag ?? ""} onChange={e => onChange({ tag: e.target.value })} className={inputCls} /></Field>
          : <p className="text-sm text-[var(--haip-fg-muted)]">{ACTION_LABELS[actionOf(data) as ActionKey] ?? "Action"}: nothing to set.</p>
      )}

      {t === "http" && (
        <>
          <Field label="Method">
            <select value={data.method ?? "POST"} onChange={e => onChange({ method: e.target.value as "POST" | "GET" })} className={inputCls}>
              <option value="POST">POST</option><option value="GET">GET</option>
            </select>
          </Field>
          <Field label="Address" hint="Must start with https://"><input type="url" value={data.url ?? ""} onChange={e => onChange({ url: e.target.value })} className={inputCls} /></Field>
          {(data.method ?? "POST") === "POST" && (
            <Field label="Body" hint={<>You can use {"{first_name}"} and {"{phone}"}.</>}>
              <textarea rows={4} value={data.body ?? ""} onChange={e => onChange({ body: e.target.value })} className={cn(inputCls, "resize-y font-mono")} />
            </Field>
          )}
        </>
      )}

      {t === "end" && <p className="text-sm text-[var(--haip-fg-muted)]">The flow stops here.</p>}
    </div>
  );
}

function QuestionFields({ data, onChange }: { data: NodeData; onChange: (p: Partial<NodeData>) => void }) {
  const saveAs = data.save_as ?? "name";
  const custom = saveAs.startsWith("custom:");
  return (
    <>
      <TextBox label="Question" value={data.content} onChange={content => onChange({ content })} placeholder="May I have your name?" />
      <Field label="Save the answer as" hint="The flow waits up to 24 hours for the answer.">
        <select value={custom ? "custom" : saveAs} onChange={e => onChange({ save_as: e.target.value === "custom" ? "custom:" : e.target.value })} className={inputCls}>
          {SAVE_AS_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          <option value="custom">A custom enquiry field</option>
        </select>
      </Field>
      {custom && (
        <Field label="Field name">
          <input value={saveAs.slice("custom:".length)} placeholder="guests_count"
            onChange={e => onChange({ save_as: `custom:${e.target.value.trim().toLowerCase().replace(/[^a-z0-9_]/g, "_")}` })} className={inputCls} />
        </Field>
      )}
    </>
  );
}

function DelayFields({ data, onChange }: { data: NodeData; onChange: (p: Partial<NodeData>) => void }) {
  const { amount, unit } = splitDelay(data.delay_minutes ?? 60);
  const per = (u: string) => DELAY_UNITS.find(d => d.value === u)?.minutes ?? 1;
  return (
    <Field label="Wait">
      <span className="flex gap-2">
        <input type="number" min={1} value={amount} aria-label="Wait amount"
          onChange={e => onChange({ delay_minutes: Math.max(1, parseInt(e.target.value) || 1) * per(unit) })} className={cn(inputCls, "w-24")} />
        <select value={unit} aria-label="Wait unit" onChange={e => onChange({ delay_minutes: amount * per(e.target.value) })} className={inputCls}>
          {DELAY_UNITS.map(u => <option key={u.value} value={u.value}>{u.label}</option>)}
        </select>
      </span>
    </Field>
  );
}
