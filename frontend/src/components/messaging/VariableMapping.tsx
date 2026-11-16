"use client";
import { useMemo } from "react";
import { cn } from "@/lib/utils";
import { WhatsAppPreview } from "./WhatsAppPreview";
import { extractVarIndices, formFromTemplate, type Template } from "./templateModel";

// How each {{n}} is filled for every recipient. Mirrors the backend's
// VARIABLE_SOURCES (wa_template_service.py).
export type VarSource = "first_name" | "name" | "phone" | "static";
export interface VarSpec { source: VarSource; value?: string; fallback?: string }
export type VariableMap = {
  header?: Record<string, VarSpec>; body?: Record<string, VarSpec>;
  coupon?: Record<string, VarSpec>;        // offer code button: "1" = the code to send
  offer?: { expires_at?: string };         // limited-time offer with a countdown: when it ends (ISO)
};
type Section = "header" | "body" | "coupon";
const SECTION_LABEL: Record<Section, string> = { header: "in the header", body: "in the body", coupon: "Offer code" };

const hasCopyCode = (t: Template) => t.components.some(c => c.type === "BUTTONS" && (c.buttons ?? []).some(b => b.type === "COPY_CODE"));
export const offerCountdown = (t: Template | undefined) =>
  !!t?.components.some(c => c.type === "LIMITED_TIME_OFFER" && c.limited_time_offer?.has_expiration);

const SOURCES: { value: VarSource; label: string }[] = [
  { value: "first_name", label: "Guest's first name" },
  { value: "name", label: "Guest's full name" },
  { value: "phone", label: "Guest's phone number" },
  { value: "static", label: "Same text for everyone" },
];

const SAMPLE = { name: "Priya Sharma", phone: "+919876543210" };

// Sections of the template that contain variables, and their indices.
export function templateSections(t: Template | undefined): { section: Section; indices: number[] }[] {
  if (!t) return [];
  const out: { section: Section; indices: number[] }[] = [];
  for (const c of t.components) {
    if (c.type !== "HEADER" && c.type !== "BODY") continue;
    const indices = extractVarIndices(c.text ?? "");
    if (indices.length) out.push({ section: c.type === "HEADER" ? "header" : "body", indices });
  }
  if (hasCopyCode(t)) out.push({ section: "coupon", indices: [1] });
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
  if (offerCountdown(t)) map.offer = { expires_at: "" };
  return map;
}

// Names like "body {{2}}" for variables that still need a value.
export function unmappedVariables(t: Template | undefined, map: VariableMap): string[] {
  const missing: string[] = [];
  for (const { section, indices } of templateSections(t)) {
    for (const i of indices) {
      const spec = map[section]?.[String(i)];
      if (!spec || (spec.source === "static" && !(spec.value ?? "").trim())) missing.push(section === "coupon" ? "the offer code" : `${section} {{${i}}}`);
    }
  }
  if (offerCountdown(t)) {
    const ends = map.offer?.expires_at ? new Date(map.offer.expires_at) : null;
    if (!ends || Number.isNaN(ends.getTime()) || ends.getTime() <= Date.now()) missing.push("when the offer ends (a future time)");
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

  const setSpec = (section: Section, index: number, spec: VarSpec) =>
    onChange({ ...value, [section]: { ...(value[section] ?? {}), [String(index)]: spec } });

  const previewForm = useMemo(() => {
    const form = formFromTemplate(template);
    for (const i of extractVarIndices(form.body)) form.bodyExamples[i] = resolveSample(value.body?.[String(i)]);
    form.headerExample = resolveSample(value.header?.["1"]);
    return form;
  }, [template, value]);

  const countdown = offerCountdown(template);
  if (sections.length === 0 && !countdown) return null;
  // datetime-local wants local "YYYY-MM-DDTHH:mm"; the map keeps the exact moment as ISO.
  const localEnds = value.offer?.expires_at ? (() => {
    const d = new Date(value.offer!.expires_at!);
    return Number.isNaN(d.getTime()) ? "" : new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  })() : "";

  return (
    <div className="grid sm:grid-cols-[minmax(0,1fr)_260px] gap-4">
      <div className="space-y-3">
        {sections.map(({ section, indices }) => indices.map(i => {
          const spec = value[section]?.[String(i)] ?? { source: "static" as VarSource, value: "" };
          return (
            <div key={`${section}${i}`} className="border border-[var(--haip-border)] rounded-xl p-3">
              <p className="text-[11px] font-semibold text-[var(--haip-fg-2)] mb-2">
                {section === "coupon" ? SECTION_LABEL.coupon : <><span className="font-mono text-primary">{`{{${i}}}`}</span> {SECTION_LABEL[section]}</>}
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
                    (spec.value ?? "").trim() ? "border-[var(--haip-border)]" : "border-[var(--haip-status-warning-border)]")} />
              ) : (
                <input value={spec.fallback ?? ""} onChange={e => setSpec(section, i, { ...spec, fallback: e.target.value })}
                  placeholder={spec.source === "phone" ? "If missing, send… (optional)" : "If we don't have it, send… (e.g. Guest)"}
                  aria-label="Fallback text"
                  className="mt-2 w-full px-2.5 py-2 border border-[var(--haip-border)] rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-primary/30" />
              )}
            </div>
          );
        }))}
        {countdown && (
          <div className="border border-[var(--haip-border)] rounded-xl p-3">
            <label htmlFor="offer-ends" className="text-[11px] font-semibold text-[var(--haip-fg-2)] block mb-2">Offer ends</label>
            <input id="offer-ends" type="datetime-local" value={localEnds}
              onChange={e => onChange({ ...value, offer: { expires_at: e.target.value ? new Date(e.target.value).toISOString() : "" } })}
              className="w-full px-2.5 py-2 border border-[var(--haip-border)] rounded-lg text-base sm:text-xs focus:outline-none focus:ring-2 focus:ring-primary/30" />
            <p className="text-[11.5px] text-[var(--haip-fg-subtle)] mt-1">Guests see a countdown to this time. Your local time.</p>
          </div>
        )}
        <p className="text-[11.5px] text-[var(--haip-fg-subtle)]">A guest with no value and no fallback is skipped, and counted as failed in the campaign.</p>
      </div>
      <div>
        <p className="text-[11px] font-semibold text-[var(--haip-fg-2)] mb-2">Preview for “{SAMPLE.name}”</p>
        <WhatsAppPreview form={previewForm} />
      </div>
    </div>
  );
}
