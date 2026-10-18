"use client";
// The visitor's answers. Choices come from the active benchmark set (GET /public/assessment/options), so a new amenity
// or season added by HAIP shows up here without a code change.
import type { ReactNode } from "react";
import type { AssessmentAnswers, AssessmentOptions, Option } from "@/lib/assessment";
import { plotSqft, segmentFor, toggle } from "@/lib/assessment";

const INPUT = "w-full min-h-[44px] rounded-xl border border-[var(--mkt-border)] bg-[var(--mkt-panel)] px-3.5 text-[16px] text-[var(--mkt-text)] outline-none focus:border-[var(--mkt-gold)] focus:bg-[var(--mkt-bg)]";
const SEGMENT_TEXT = { small: "Small property (under 5,000 sq ft)", medium: "Medium property (5,000 sq ft to 1 acre)", large: "Large property (1 acre or more)" };

function Label({ text, children, hint }: { text: string; children: ReactNode; hint?: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 inline-block text-[13px] font-semibold text-[var(--mkt-muted)]">{text}</span>
      {children}
      {hint && <span className="mt-1 block text-[12px] text-[var(--mkt-muted)]">{hint}</span>}
    </label>
  );
}

function Chips({ options, selected, onToggle, label }: { options: Option[]; selected: string[]; onToggle: (k: string) => void; label: string }) {
  return (
    <fieldset>
      <legend className="mb-2 text-[13px] font-semibold text-[var(--mkt-muted)]">{label}</legend>
      <div className="flex flex-wrap gap-2">
        {options.map(o => {
          const on = selected.includes(o.key);
          return (
            <button key={o.key} type="button" aria-pressed={on} onClick={() => onToggle(o.key)}
              className={`min-h-[44px] rounded-full border px-4 text-[14px] font-semibold transition-colors ${on
                ? "border-[var(--mkt-gold)] bg-[var(--mkt-surface)] text-[var(--mkt-gold)]"
                : "border-[var(--mkt-border)] bg-[var(--mkt-bg)] text-[var(--mkt-muted)]"}`}>
              {o.label}
            </button>
          );
        })}
      </div>
    </fieldset>
  );
}

export function AnswersForm({ value, onChange, options }: {
  value: AssessmentAnswers;
  onChange: (next: AssessmentAnswers) => void;
  options: AssessmentOptions;
}) {
  const set = <K extends keyof AssessmentAnswers>(k: K, v: AssessmentAnswers[K]) => onChange({ ...value, [k]: v });
  const num = (s: string) => (s === "" ? NaN : Number(s));
  const sqft = plotSqft(value);
  const segment = Number.isFinite(sqft) && sqft > 0 ? segmentFor(sqft, options.segments) : null;

  return (
    <div className="space-y-5">
      <fieldset>
        <legend className="mb-2 text-[13px] font-semibold text-[var(--mkt-muted)]">What kind of property?</legend>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {options.property_types.map(o => {
            const on = value.property_type === o.key;
            return (
              <button key={o.key} type="button" aria-pressed={on} onClick={() => set("property_type", o.key as AssessmentAnswers["property_type"])}
                className={`min-h-[48px] rounded-xl border px-3 text-[14px] font-semibold ${on
                  ? "border-[var(--mkt-gold)] bg-[var(--mkt-surface)] text-[var(--mkt-gold)]"
                  : "border-[var(--mkt-border)] bg-[var(--mkt-bg)] text-[var(--mkt-text)]"}`}>
                {o.label}
              </button>
            );
          })}
        </div>
      </fieldset>

      <div>
      <div className="grid grid-cols-[1fr_auto] gap-2 items-end">
        <Label text="Plot size">
          <input type="number" inputMode="decimal" min={0} step="any" className={INPUT}
            value={Number.isFinite(value.plot_size) ? value.plot_size : ""} onChange={e => set("plot_size", num(e.target.value))} />
        </Label>
        <div className="flex h-[44px] rounded-xl border border-[var(--mkt-border)] overflow-hidden" role="group" aria-label="Plot unit">
          {(["sqft", "acres"] as const).map(u => (
            <button key={u} type="button" aria-pressed={value.plot_unit === u} onClick={() => set("plot_unit", u)}
              className={`px-3.5 text-[14px] font-semibold ${value.plot_unit === u ? "bg-[var(--mkt-gold)] text-white" : "bg-[var(--mkt-bg)] text-[var(--mkt-muted)]"}`}>
              {u === "sqft" ? "sq ft" : "acres"}
            </button>
          ))}
        </div>
      </div>
      {segment && <p className="mt-1 text-[12px] text-[var(--mkt-muted)]">{SEGMENT_TEXT[segment]}</p>}
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <Label text="Rooms / units" hint={value.property_type === "event_space" ? "0 is fine for a venue without stays." : undefined}>
          <input type="number" inputMode="numeric" min={0} max={300} step={1} className={INPUT}
            value={Number.isFinite(value.rooms) ? value.rooms : ""} onChange={e => set("rooms", num(e.target.value))} />
        </Label>
        <Label text="New build or conversion?">
          <select className={INPUT} value={value.build_status} onChange={e => set("build_status", e.target.value as AssessmentAnswers["build_status"])}>
            <option value="new">New build</option>
            <option value="conversion">Converting an existing building</option>
          </select>
        </Label>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <Label text="Town or city">
          <input className={INPUT} value={value.city} maxLength={80} placeholder="e.g. Madikeri" onChange={e => set("city", e.target.value)} />
        </Label>
        <Label text="District (optional)">
          <input className={INPUT} value={value.district ?? ""} maxLength={80} placeholder="e.g. Kodagu" onChange={e => set("district", e.target.value)} />
        </Label>
      </div>

      <div className="grid grid-cols-[1fr_7.5rem] gap-2">
        <Label text="Nearest">
          <select className={INPUT} value={value.landmark} onChange={e => set("landmark", e.target.value as AssessmentAnswers["landmark"])}>
            {options.landmarks.map(o => <option key={o.key} value={o.key}>{o.label.replace(/^(a|an) /, "").replace(/^./, c => c.toUpperCase())}</option>)}
          </select>
        </Label>
        <Label text="Distance (km)">
          <input type="number" inputMode="decimal" min={0} max={500} step="any" className={INPUT}
            value={Number.isFinite(value.landmark_km) ? value.landmark_km : ""} onChange={e => set("landmark_km", num(e.target.value))} />
        </Label>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <Label text="Season pattern">
          <select className={INPUT} value={value.seasonality} onChange={e => set("seasonality", e.target.value)}>
            {options.seasonality.map(o => <option key={o.key} value={o.key}>{o.label}</option>)}
          </select>
        </Label>
        <Label text="Competition nearby">
          <select className={INPUT} value={value.competitor_density} onChange={e => set("competitor_density", e.target.value as AssessmentAnswers["competitor_density"])}>
            {options.competitor_density.map(o => <option key={o.key} value={o.key}>{o.label}</option>)}
          </select>
        </Label>
      </div>

      <Chips label="Amenities" options={options.amenities} selected={value.amenities} onToggle={k => set("amenities", toggle(value.amenities, k))} />
      <Chips label="Experiences you offer" options={options.experiences} selected={value.experiences} onToggle={k => set("experiences", toggle(value.experiences, k))} />
    </div>
  );
}
