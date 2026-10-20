"use client";
// The filter controls on the Reports page. The backend sends each report's
// filters (see GET /reports/catalog); this draws them: a chip row for "pick
// any of these" (source, stage), Any / Yes / No for yes-or-no questions
// ("shared a phone number"), a dropdown for one-of, and a box for the rest.
import { cn } from "@/lib/utils";

export type FilterValue = string | string[];

export interface FilterOption { value: string; label: string }

export interface FilterDef {
  key: string;
  label: string;
  type: "select" | "multiselect" | "text" | "number" | "boolean";
  // Older reports send plain strings; the leads report sends {value, label}.
  options?: Array<string | FilterOption>;
}

export function optionList(def: FilterDef): FilterOption[] {
  return (def.options ?? [])
    .map(o => (typeof o === "string" ? { value: o, label: o } : o))
    .filter(o => o.value !== "All");
}

/** Drop the filters left on "Any" so the request only carries real choices. */
export function activeFilters(vals: Record<string, FilterValue>): Record<string, FilterValue> {
  const out: Record<string, FilterValue> = {};
  for (const [k, v] of Object.entries(vals)) {
    if (Array.isArray(v) ? v.length > 0 : v !== "" && v != null) out[k] = v;
  }
  return out;
}

const box =
  "w-full px-3 py-2 border border-[var(--haip-border)] rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary/30";

export function FilterControl({
  def, value, onChange,
}: {
  def: FilterDef;
  value: FilterValue | undefined;
  onChange: (v: FilterValue) => void;
}) {
  const options = optionList(def);

  if (def.type === "boolean") {
    const current = typeof value === "string" ? value : "";
    return (
      <div role="group" aria-label={def.label} className="inline-flex rounded-lg border border-[var(--haip-border)] bg-[var(--haip-surface)] p-0.5">
        {[["", "Any"], ["true", "Yes"], ["false", "No"]].map(([v, label]) => (
          <button
            key={v || "any"} type="button" aria-pressed={current === v}
            onClick={() => onChange(v)}
            className={cn(
              "px-3 py-1 rounded-md text-xs font-semibold transition-colors outline-none focus-visible:ring-2 focus-visible:ring-primary",
              current === v
                ? v === "true" ? "bg-primary text-white" : v === "false" ? "bg-gray-700 text-white" : "bg-white text-[var(--haip-fg)] shadow-sm"
                : "text-[var(--haip-fg-subtle)] hover:text-[var(--haip-fg)]",
            )}
          >
            {label}
          </button>
        ))}
      </div>
    );
  }

  if (def.type === "multiselect") {
    const picked = Array.isArray(value) ? value : [];
    const toggle = (v: string) => onChange(picked.includes(v) ? picked.filter(p => p !== v) : [...picked, v]);
    return (
      <div className="flex flex-wrap items-center gap-1.5">
        {options.map(o => {
          const on = picked.includes(o.value);
          return (
            <button
              key={o.value} type="button" aria-pressed={on} onClick={() => toggle(o.value)}
              className={cn(
                "px-2.5 py-1 rounded-full border text-xs font-medium transition-colors outline-none focus-visible:ring-2 focus-visible:ring-primary",
                on ? "border-primary bg-[var(--haip-primary-tint)] text-[var(--accent-foreground)]" : "border-[var(--haip-border)] bg-white text-[var(--haip-fg-muted)] hover:border-[var(--haip-border-strong)]",
              )}
            >
              {o.label}
            </button>
          );
        })}
        {picked.length > 0 && (
          <button type="button" onClick={() => onChange([])} className="text-[11px] text-[var(--haip-fg-subtle)] hover:text-[var(--haip-fg-2)] hover:underline ml-1">
            Clear
          </button>
        )}
      </div>
    );
  }

  if (def.type === "select") {
    return (
      <select
        value={typeof value === "string" ? value : ""}
        onChange={e => onChange(e.target.value)}
        aria-label={def.label} className={box}
      >
        <option value="">All</option>
        {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    );
  }

  return (
    <input
      type={def.type === "number" ? "number" : "text"}
      value={typeof value === "string" ? value : ""}
      onChange={e => onChange(e.target.value)}
      aria-label={def.label}
      placeholder={`Filter by ${def.label.toLowerCase()}`}
      className={box}
    />
  );
}
