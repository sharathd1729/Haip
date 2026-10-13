"use client";
import { useState } from "react";
import { Plus, Trash2, X } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { blankFor, type Field, type Json, type Option } from "./businessDataSpecs";

export interface EditorContext {
  destinations: Option[];
  packages: Option[];
  vehicles: Option[];
}

const INPUT =
  "w-full min-h-11 rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-base sm:min-h-9 sm:text-[13px] " +
  "text-[var(--haip-fg)] placeholder:text-[var(--haip-text-subtle)] focus:outline-none focus:ring-2 focus:ring-primary/30";

function Label({ field, children }: { field: Field; children: React.ReactNode }) {
  const required = "required" in field && field.required;
  return (
    <div className="space-y-1">
      <label className="block text-xs font-semibold text-[var(--haip-fg-2)]">
        {field.label}
        {required && <span className="text-[var(--haip-red)]"> *</span>}
      </label>
      {children}
      {"hint" in field && field.hint && <p className="text-[11px] leading-snug text-[var(--haip-fg-subtle)]">{field.hint}</p>}
    </div>
  );
}

function Chips({ options, value, onChange, label }: { options: Option[]; value: string[]; onChange: (v: string[]) => void; label: string }) {
  if (options.length === 0) return <p className="text-xs text-[var(--haip-fg-subtle)]">Nothing to choose from yet.</p>;
  return (
    <div role="group" aria-label={label} className="flex flex-wrap gap-1.5">
      {options.map(o => {
        const on = value.includes(o.value);
        return (
          <button
            key={o.value} type="button" aria-pressed={on}
            onClick={() => onChange(on ? value.filter(x => x !== o.value) : [...value, o.value])}
            className={cn(
              "min-h-11 rounded-lg border px-3 text-xs font-medium transition-colors sm:min-h-8",
              on ? "border-primary/40 bg-primary/10 text-primary" : "border-[var(--haip-border)] bg-[var(--haip-card)] text-[var(--haip-fg-2)] hover:border-[var(--haip-border-strong)]",
            )}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

function Tags({ value, onChange, placeholder, label }: { value: string[]; onChange: (v: string[]) => void; placeholder?: string; label: string }) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const t = draft.trim();
    if (t && !value.includes(t)) onChange([...value, t]);
    setDraft("");
  };
  return (
    <div className="space-y-2">
      {value.length > 0 && (
        <ul className="flex flex-wrap gap-1.5">
          {value.map(t => (
            <li key={t} className="inline-flex items-center gap-1 rounded-full border border-[var(--haip-border)] bg-[var(--haip-surface)] py-1 pl-3 pr-1 text-xs">
              {t}
              <button type="button" aria-label={`Remove ${t}`} onClick={() => onChange(value.filter(x => x !== t))}
                className="flex h-6 w-6 items-center justify-center rounded-full text-[var(--haip-fg-subtle)] hover:bg-[var(--haip-border)]">
                <X size={12} />
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex gap-2">
        <input
          aria-label={`Add to ${label}`} value={draft} placeholder={placeholder} className={INPUT}
          onChange={e => setDraft(e.target.value)}
          onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); add(); } }}
        />
        <button type="button" onClick={add} disabled={!draft.trim()}
          className="min-h-11 shrink-0 rounded-lg border border-[var(--haip-border)] px-3 text-xs font-semibold hover:bg-[var(--haip-surface)] disabled:opacity-40 sm:min-h-9">
          Add
        </button>
      </div>
    </div>
  );
}

/** Renders the inputs for a list of field specs and reports every change as a whole new value object. */
export function FieldEditor({ fields, value, onChange, ctx }: { fields: Field[]; value: Json; onChange: (v: Json) => void; ctx: EditorContext }) {
  const set = (name: string, v: unknown) => onChange({ ...value, [name]: v });
  return (
    <div className="space-y-4">
      {fields.map(f => {
        const v = value[f.name];
        switch (f.k) {
          case "text":
            return (
              <Label key={f.name} field={f}>
                {f.multiline
                  ? <textarea rows={3} maxLength={f.max} value={String(v ?? "")} onChange={e => set(f.name, e.target.value)} className={cn(INPUT, "py-2")} />
                  : <input maxLength={f.max} value={String(v ?? "")} onChange={e => set(f.name, e.target.value)} className={INPUT} />}
              </Label>
            );
          case "time":
            return <Label key={f.name} field={f}><input type="time" value={String(v ?? "")} onChange={e => set(f.name, e.target.value)} className={INPUT} /></Label>;
          case "date":
            return <Label key={f.name} field={f}><input type="date" value={String(v ?? "")} onChange={e => set(f.name, e.target.value)} className={INPUT} /></Label>;
          case "int":
            return (
              <Label key={f.name} field={f}>
                <input type="number" inputMode="numeric" min={f.min} max={f.max} value={String(v ?? "")} onChange={e => set(f.name, e.target.value)} className={INPUT} />
              </Label>
            );
          case "decimal":
            return (
              <Label key={f.name} field={f}>
                <div className="relative">
                  <input inputMode="decimal" value={String(v ?? "")} onChange={e => set(f.name, e.target.value.replace(/[^0-9.]/g, ""))}
                    className={cn(INPUT, f.unit && "pr-14")} />
                  {f.unit && <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-xs text-[var(--haip-fg-subtle)]">{f.unit}</span>}
                </div>
              </Label>
            );
          case "bool":
            return (
              <label key={f.name} className="flex min-h-11 cursor-pointer items-start gap-2.5 py-1 sm:min-h-0">
                <input type="checkbox" checked={!!v} onChange={e => set(f.name, e.target.checked)} className="mt-0.5 h-5 w-5 shrink-0 accent-[var(--primary)] sm:h-4 sm:w-4" />
                <span>
                  <span className="text-xs font-semibold text-[var(--haip-fg-2)]">{f.label}</span>
                  {f.hint && <span className="block text-[11px] leading-snug text-[var(--haip-fg-subtle)]">{f.hint}</span>}
                </span>
              </label>
            );
          case "select":
            return (
              <Label key={f.name} field={f}>
                <select value={String(v ?? "")} onChange={e => set(f.name, e.target.value)} className={INPUT}>
                  {!f.required && <option value="">—</option>}
                  {f.options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              </Label>
            );
          case "key":
            return (
              <Label key={f.name} field={f}>
                <select value={String(v ?? "")} onChange={e => set(f.name, e.target.value)} className={INPUT}>
                  <option value="">Choose…</option>
                  {ctx.destinations.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              </Label>
            );
          case "tags":
            return <Label key={f.name} field={f}><Tags label={f.label} placeholder={f.placeholder} value={(v as string[]) ?? []} onChange={x => set(f.name, x)} /></Label>;
          case "choices":
            return <Label key={f.name} field={f}><Chips label={f.label} options={f.options} value={(v as string[]) ?? []} onChange={x => set(f.name, x)} /></Label>;
          case "keys":
            return <Label key={f.name} field={f}><Chips label={f.label} options={f.of === "destination" ? ctx.destinations : ctx.packages} value={(v as string[]) ?? []} onChange={x => set(f.name, x)} /></Label>;
          case "vehicles":
            return <Label key={f.name} field={f}><Chips label={f.label} options={ctx.vehicles} value={(v as string[]) ?? []} onChange={x => set(f.name, x)} /></Label>;
          case "object": {
            const on = v != null && typeof v === "object";
            return (
              <div key={f.name} className="space-y-3 rounded-xl border border-[var(--haip-border)] p-3">
                <label className="flex min-h-11 cursor-pointer items-center gap-2.5 sm:min-h-0">
                  <input type="checkbox" checked={on} className="h-5 w-5 accent-[var(--primary)] sm:h-4 sm:w-4"
                    onChange={e => set(f.name, e.target.checked ? blankFor(f.fields) : undefined)} />
                  <span className="text-xs font-semibold text-[var(--haip-fg-2)]">{f.toggle}</span>
                </label>
                {on && <FieldEditor fields={f.fields} value={v as Json} ctx={ctx} onChange={x => set(f.name, x)} />}
              </div>
            );
          }
          case "list": {
            const rows = (Array.isArray(v) ? v : []) as Json[];
            return (
              <fieldset key={f.name} className="space-y-3">
                <legend className="text-xs font-semibold text-[var(--haip-fg-2)]">{f.label}</legend>
                {rows.map((row, i) => (
                  <div key={i} className="space-y-3 rounded-xl border border-[var(--haip-border)] bg-[var(--haip-surface)] p-3">
                    <div className="flex items-center justify-between">
                      <span className="text-[11px] font-bold uppercase tracking-wider text-[var(--haip-fg-subtle)]">{f.itemLabel} {i + 1}</span>
                      {rows.length > (f.min ?? 0) && (
                        <button type="button" aria-label={`Remove ${f.itemLabel.toLowerCase()} ${i + 1}`} onClick={() => set(f.name, rows.filter((_, j) => j !== i))}
                          className="flex h-11 w-11 items-center justify-center rounded-lg text-[var(--haip-fg-subtle)] hover:bg-[var(--haip-border)] sm:h-8 sm:w-8">
                          <Trash2 size={14} />
                        </button>
                      )}
                    </div>
                    <FieldEditor fields={f.fields} value={row} ctx={ctx} onChange={x => set(f.name, rows.map((r, j) => (j === i ? x : r)))} />
                  </div>
                ))}
                <button type="button" onClick={() => set(f.name, [...rows, blankFor(f.fields)])}
                  className="flex min-h-11 items-center gap-1.5 rounded-lg border border-dashed border-[var(--haip-border-strong)] px-3 text-xs font-semibold text-[var(--haip-fg-2)] hover:bg-[var(--haip-surface)] sm:min-h-9">
                  <Plus size={13} /> {f.addLabel}
                </button>
              </fieldset>
            );
          }
        }
      })}
    </div>
  );
}
