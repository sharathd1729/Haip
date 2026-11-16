"use client";
// One guest's fields on the guest details form: name, age (if the workspace asks), nationality, an ID, and for a guest who
// is not an Indian citizen the passport + visa details and photos Form C needs. Photos upload one by one to private storage
// before the form is sent (POST .../photo). Moved out of GuestDetailsForm (workspace redesign Phase 4); behaviour unchanged.
import { useState } from "react";
import { StatusPill } from "@/components/ui/kit";

export const field = "min-h-12 w-full rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-[16px] text-[var(--haip-fg)]";
export const lbl = "flex flex-col gap-1.5 text-[14px] font-semibold text-[var(--haip-fg)]";
export const hint = "text-[13px] font-normal text-[var(--haip-fg-subtle)]";
const MAX_PHOTO = 5 * 1024 * 1024;
const PHOTO_TYPES = "image/jpeg,image/png,image/webp,application/pdf";

export interface Option { value: string; label: string }
export interface Person {
  name: string; age: string; nationality: string; id_type: string; id_number: string;
  passport_number: string; passport_expires_on: string; visa_type: string; visa_number: string; visa_expires_on: string;
  arrived_india_on: string; arrived_from: string; onward_to: string; passport_photo_id: string; visa_photo_id: string;
}

export const blankPerson = (nationality: string): Person => ({
  name: "", age: "", nationality, id_type: "aadhaar", id_number: "", passport_number: "", passport_expires_on: "",
  visa_type: "", visa_number: "", visa_expires_on: "", arrived_india_on: "", arrived_from: "", onward_to: "",
  passport_photo_id: "", visa_photo_id: "",
});

/** Enough for the checklist to tick this guest (the server checks every rule again on send). */
export function personDone(p: Person, ageRequired: boolean, noVisa: string[]): boolean {
  if (!p.name.trim() || !p.nationality || (ageRequired && !p.age.trim())) return false;
  if (p.nationality === "IN") return p.id_number.replace(/\D/g, "").length >= 4 || p.id_number.trim().length >= 5;
  if (noVisa.includes(p.nationality) && !p.passport_number) return p.id_number.trim().length >= 4;
  return !!(p.passport_number && p.passport_expires_on && p.arrived_india_on);
}

function PhotoField({ url, kind, label, value, onDone }: {
  url: string; kind: "passport" | "visa"; label: string; value: string; onDone: (id: string) => void;
}) {
  const [state, setState] = useState<"idle" | "busy" | "error">("idle");
  const [error, setError] = useState<string | null>(null);
  const pick = async (file: File | undefined) => {
    if (!file) return;
    if (file.size > MAX_PHOTO) { setState("error"); setError("The photo is larger than 5 MB."); return; }
    setState("busy"); setError(null);
    const body = new FormData();
    body.append("kind", kind);
    body.append("file", file);
    try {
      const r = await fetch(`${url}/photo`, { method: "POST", body });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) { setState("error"); setError(typeof data?.detail === "string" ? data.detail : "Couldn't add the photo. Try again."); return; }
      onDone(data.photo_id); setState("idle");
    } catch { setState("error"); setError("No connection. Please try again."); }
  };
  return (
    <div className={lbl}>
      <span className="flex items-center justify-between gap-2">{label}
        {value && state !== "busy" && <StatusPill tone="success">Added</StatusPill>}
      </span>
      <label className="haip-btn-secondary flex min-h-12 cursor-pointer items-center justify-center text-[15px]">
        {state === "busy" ? "Adding…" : value ? "Replace photo" : "Take or choose a photo"}
        <input type="file" accept={PHOTO_TYPES} className="sr-only" disabled={state === "busy"}
          onChange={e => { pick(e.target.files?.[0]); e.target.value = ""; }} />
      </label>
      <span className={hint}>JPG, PNG, WebP or PDF, up to 5 MB. Kept private.</span>
      {error && <span role="alert" className="text-[13.5px] font-normal text-[var(--haip-status-danger-fg)]">{error}</span>}
    </div>
  );
}

export function PersonFields({ p, i, url, ask, idTypes, countries, noVisa, visaTypes, word, set }: {
  p: Person; i: number; url: string; ask: "off" | "ask" | "req"; idTypes: Option[]; countries: Option[]; noVisa: string[];
  visaTypes: Option[]; word: string; set: (i: number, k: keyof Person, v: string) => void;
}) {
  const on = (k: keyof Person) => (e: { target: { value: string } }) => set(i, k, e.target.value);
  const abroad = p.nationality !== "IN";
  const free = noVisa.includes(p.nationality);
  const oci = p.visa_type === "oci";
  return (
    <div className="flex flex-col gap-3">
      <label className={lbl}>Full name (as on the ID)<input className={field} value={p.name} onChange={on("name")} autoComplete="off" /></label>
      <div className="grid grid-cols-2 gap-3">
        {ask !== "off" && (
          <label className={lbl}><span>Age{ask === "ask" ? <span className={hint}> (optional)</span> : null}</span>
            <input className={field} inputMode="numeric" pattern="[0-9]*" value={p.age} onChange={on("age")} />
          </label>
        )}
        <label className={`${lbl} ${ask === "off" ? "col-span-2" : ""}`}>Nationality
          <select className={field} value={p.nationality} onChange={on("nationality")}>
            {p.nationality === "" && <option value="">Choose</option>}
            <option value="IN">India</option>
            {countries.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
          </select>
        </label>
      </div>
      {(!abroad || (free && !p.passport_number)) && (
        <>
          <div role="radiogroup" aria-label={`Guest ${i + 1} ID type`} className="flex flex-wrap gap-2">
            {idTypes.map(t => (
              <button key={t.value} type="button" role="radio" aria-checked={p.id_type === t.value} onClick={() => set(i, "id_type", t.value)}
                className={`min-h-11 rounded-full border px-4 text-[14px] ${p.id_type === t.value
                  ? "border-primary bg-primary font-semibold text-primary-foreground" : "border-[var(--haip-border)] bg-[var(--haip-card)] text-[var(--haip-fg)]"}`}>
                {t.label}
              </button>
            ))}
          </div>
          <label className={lbl}>{idTypes.find(t => t.value === p.id_type)?.label ?? "ID"} number
            <input className={field} value={p.id_number} onChange={on("id_number")} autoComplete="off"
              inputMode={p.id_type === "aadhaar" ? "numeric" : "text"} />
            {p.id_type === "aadhaar" && <span className={hint}>We keep only the last 4 digits.</span>}
          </label>
        </>
      )}
      {abroad && p.nationality !== "" && (
        <fieldset className="flex flex-col gap-3 rounded-xl border border-[var(--haip-border)] p-3">
          <legend className="px-1 text-[14px] font-semibold">Passport and visa</legend>
          <p className={hint}>
            Indian law asks us to register guests who are not Indian citizens with the Bureau of Immigration (Form C) within
            24 hours of arrival. Your numbers are stored encrypted and seen only by the team member who files it.
            {free ? " Citizens of Nepal and Bhutan need no visa; the passport is optional (give another ID above instead)." : ""}
          </p>
          <label className={lbl}>Passport number{free ? " (optional)" : ""}
            <input className={field} value={p.passport_number} onChange={on("passport_number")} autoComplete="off" autoCapitalize="characters" />
          </label>
          {(!free || p.passport_number) && (
            <>
              <label className={lbl}>Passport expiry date<input type="date" className={field} value={p.passport_expires_on} onChange={on("passport_expires_on")} /></label>
              <PhotoField url={url} kind="passport" label="Photo of the passport page with your photo" value={p.passport_photo_id}
                onDone={id => set(i, "passport_photo_id", id)} />
            </>
          )}
          <label className={lbl}>Visa type{free ? " (optional)" : ""}
            <select className={field} value={p.visa_type} onChange={on("visa_type")}>
              <option value="">{free ? "No visa" : "Choose"}</option>
              {visaTypes.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
          </label>
          {p.visa_type && (
            <>
              <label className={lbl}>{oci ? "OCI card number" : "Visa number"}
                <input className={field} value={p.visa_number} onChange={on("visa_number")} autoComplete="off" autoCapitalize="characters" />
              </label>
              {!oci && <label className={lbl}>Visa expiry date<input type="date" className={field} value={p.visa_expires_on} onChange={on("visa_expires_on")} /></label>}
              <PhotoField url={url} kind="visa" label={oci ? "Photo of the OCI card" : "Photo of the visa"} value={p.visa_photo_id}
                onDone={id => set(i, "visa_photo_id", id)} />
            </>
          )}
          <label className={lbl}>Date you arrived in India<input type="date" className={field} value={p.arrived_india_on} onChange={on("arrived_india_on")} /></label>
          <label className={lbl}>Arrived in India from (city, country)<input className={field} value={p.arrived_from} onChange={on("arrived_from")} /></label>
          <label className={lbl}>Where you go after this {word} (city, country)<input className={field} value={p.onward_to} onChange={on("onward_to")} /></label>
        </fieldset>
      )}
    </div>
  );
}
