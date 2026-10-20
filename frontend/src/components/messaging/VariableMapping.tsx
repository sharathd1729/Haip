"use client";
import { useMemo } from "react";
import { cn } from "@/lib/utils";
import { WhatsAppPreview } from "./WhatsAppPreview";
import { extractVarIndices, formFromTemplate, type Template } from "./templateModel";

// How each {{n}} is filled for every recipient. Mirrors the backend's
// VARIABLE_SOURCES (wa_template_service.py).
export type VarSource = "first_name" | "name" | "phone" | "static";
export interface VarSpec { source: VarSource; value?: string; fallback?: string }
export type VariableMap = { header?: Record<string, VarSpec>; body?: Record<string, VarSpec> };

const SOURCES: { value: VarSource; label: string }[] = [
  { value: "first_name", label: "Guest's first name" },
  { value: "name", label: "Guest's full name" },
  { value: "phone", label: "Guest's phone number" },
  { value: "static", label: "Same text for everyone" },
];

const SAMPLE = { name: "Priya Sharma", phone: "+919876543210" };

// Sections of the template that contain variables, and their indices.
export function templateSections(t: Template | undefined): { section: "header" | "body"; indices: number[] }[] {
  if (!t) return [];
  const out: { section: "header" | "body"; indices: number[] }[] = [];
  for (const c of t.components) {
    if (c.type !== "HEADER" && c.type !== "BODY") continue;
    const indices = extractVarIndices(c.text ?? "");
    if (indices.length) out.push({ section: c.type === "HEADER" ? "header" : "body", indices });
  }
  return out;
}

export function defaultMap(t: Template | undefined): VariableMap {
  const map: VariableMap = {};
  for (const { section, indices } of templateSections(t)) {
    map[section] = {};
    indices.forEach((i, pos) => {
      map[section]![String(i)] = pos === 0 && section === "body"
        ? { source: "first_name", fallback: "Guest" }
        : { source: "static", value: "" };
    });
  }
  return map;
}

// Names like "body {{2}}" for variables that still need a value.
export function unmappedVariables(t: Template | undefined, map: VariableMap): string[] {
  const missing: string[] = [];
  for (const { section, indices } of templateSections(t)) {
    for (const i of indices) {
      const spec = map[section]?.[String(i)];
      if (!spec || (spec.source === "static" && !(spec.value ?? "").trim())) missing.push(`${section} {{${i}}}`);
    }
  }
  return missing;
}

function resolveSample(spec: VarSpec | undefined): string {
  if (!spec) return "";
  const raw = spec.source === "static" ? spec.value ?? ""
    : spec.source === "name" ? SAMPLE.name
    : spec.source === "first_name" ? SAMPLE.name.split(" ")[0]
    : SAMPLE.phone;
  return raw.trim() || (spec.fallback ?? "");
}

export function VariableMapping({ template, value, onChange }: {
  template: Template;
  value: VariableMap;
  onChange: (next: VariableMap) => void;
}) {
  const sections = templateSections(template);

  const setSpec = (section: "header" | "body", index: number, spec: VarSpec) =>
    onChange({ ...value, [section]: { ...(value[section] ?? {}), [String(index)]: spec } });

  const previewForm = useMemo(() => {
    const form = formFromTemplate(template);
    for (const i of extractVarIndices(form.body)) form.bodyExamples[i] = resolveSample(value.body?.[String(i)]);
    form.headerExample = resolveSample(value.header?.["1"]);
    return form;
  }, [template, value]);

  if (sections.length === 0) return null;

  return (
    <div className="grid sm:grid-cols-[minmax(0,1fr)_260px] gap-4">
      <div className="space-y-3">
        {sections.map(({ section, indices }) => indices.map(i => {
          const spec = value[section]?.[String(i)] ?? { source: "static" as VarSource, value: "" };
          return (
            <div key={`${section}${i}`} className="border border-[var(--haip-border)] rounded-xl p-3">
              <p className="text-[11px] font-semibold text-[var(--haip-fg-2)] mb-2">
                <span className="font-mono text-primary">{`{{${i}}}`}</span> in the {section}
              </p>
              <select value={spec.source} aria-label={`What to put in ${section} variable ${i}`}
                onChange={e => setSpec(section, i, { source: e.target.value as VarSource, value: spec.value, fallback: spec.fallback })}
                className="w-full px-2.5 py-2 border border-[var(--haip-border)] rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-primary/30">
                {SOURCES.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
              </select>
              {spec.source === "static" ? (
                <input value={spec.value ?? ""} onChange={e => setSpec(section, i, { ...spec, value: e.target.value })}
                  placeholder="Text to send" aria-label="Text to send"
                  className={cn("mt-2 w-full px-2.5 py-2 border rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-primary/30",
                    (spec.value ?? "").trim() ? "border-[var(--haip-border)]" : "border-amber-300")} />
              ) : (
                <input value={spec.fallback ?? ""} onChange={e => setSpec(section, i, { ...spec, fallback: e.target.value })}
                  placeholder={spec.source === "phone" ? "If missing, send… (optional)" : "If we don't have it, send… (e.g. Guest)"}
                  aria-label="Fallback text"
                  className="mt-2 w-full px-2.5 py-2 border border-[var(--haip-border)] rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-primary/30" />
              )}
            </div>
          );
        }))}
        <p className="text-[10px] text-[var(--haip-fg-subtle)]">A guest with no value and no fallback is skipped, and counted as failed in the campaign.</p>
      </div>
      <div>
        <p className="text-[11px] font-semibold text-[var(--haip-fg-2)] mb-2">Preview for “{SAMPLE.name}”</p>
        <WhatsAppPreview form={previewForm} />
      </div>
    </div>
  );
}
