"use client";
// The guest's private details form (no login), for a caravan trip (/r/trip/<token>) or a villa stay (/r/stay/<token>):
// names, ages, nationality and ID of everyone, an emergency contact, food notes and requests, then a typed signature under
// the consent text of a stated version. A guest who is not an Indian citizen also gives passport + visa details and photos
// (what Form C needs). Photos upload one by one to private storage before the form is sent. Backend:
// GET/POST /api/v1/public/ops/guest-form/{token} + POST .../photo (ops_guest_form; Aadhaar keeps only the last 4 digits,
// passport / visa numbers are stored encrypted). Phone first, 16px inputs, 48px buttons.
import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { Card, CardBody, CardHeader, EmptyState, StatusPill } from "@/components/ui/kit";
import { countryName } from "@/lib/ops";

const _raw = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
const API = _raw.endsWith("/api/v1") ? _raw : `${_raw}/api/v1`;
const field = "min-h-12 w-full rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-[16px] text-[var(--haip-fg)]";
const lbl = "flex flex-col gap-1.5 text-[14px] font-semibold text-[var(--haip-fg)]";
const hint = "text-[13px] font-normal text-[var(--haip-fg-subtle)]";
const MAX_PHOTO = 5 * 1024 * 1024;
const PHOTO_TYPES = "image/jpeg,image/png,image/webp,application/pdf";

interface Option { value: string; label: string }
interface View {
  guest_first_name: string; check_in: string; check_out: string; party: number; submitted: boolean;
  file_word: "trip" | "stay"; unit_word: string; place: string | null; guest_from_abroad: boolean;
  id_types: Option[]; countries: string[]; no_visa_needed: string[]; visa_types: Option[];
  consent: { version: string; text: string };
}
interface Person {
  name: string; age: string; nationality: string; id_type: string; id_number: string;
  passport_number: string; passport_expires_on: string; visa_type: string; visa_number: string; visa_expires_on: string;
  arrived_india_on: string; arrived_from: string; onward_to: string; passport_photo_id: string; visa_photo_id: string;
}

const blank = (nationality: string): Person => ({
  name: "", age: "", nationality, id_type: "aadhaar", id_number: "", passport_number: "", passport_expires_on: "",
  visa_type: "", visa_number: "", visa_expires_on: "", arrived_india_on: "", arrived_from: "", onward_to: "",
  passport_photo_id: "", visa_photo_id: "",
});
const day = (iso: string) => new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "UTC" });

/** One passport / visa photo: uploads as soon as it is chosen, so the guest sees at once if it was refused. */
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

export default function GuestDetailsForm() {
  const { token } = useParams<{ token: string }>();
  const url = `${API}/public/ops/guest-form/${encodeURIComponent(token)}`;
  const [view, setView] = useState<View | null>(null);
  const [state, setState] = useState<"loading" | "bad" | "ready" | "sent">("loading");
  const [people, setPeople] = useState<Person[]>([]);
  const [f, setF] = useState({ emergency_name: "", emergency_phone: "", food: "", requests: "", signed_name: "", agreed: false });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetch(url).then(async r => {
      if (!r.ok) { setState("bad"); return; }
      const v: View = await r.json();
      setView(v);
      // A website booking said the guest is from abroad: the first guest picks their nationality instead of "India".
      setPeople(Array.from({ length: v.party }, (_, i) => blank(v.guest_from_abroad && i === 0 ? "" : "IN")));
      setState(v.submitted ? "sent" : "ready");
    }).catch(() => setState("bad"));
  }, [url]);

  const countries = useMemo(() => (view?.countries ?? []).filter(c => c !== "IN")
    .map(c => ({ value: c, label: countryName(c) })).sort((a, b) => a.label.localeCompare(b.label)), [view]);
  const set = (i: number, k: keyof Person, v: string) => setPeople(ps => ps.map((p, n) => (n === i ? { ...p, [k]: v } : p)));
  const person = (i: number, k: keyof Person) => (e: { target: { value: string } }) => set(i, k, e.target.value);
  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const r = await fetch(url, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...f, guests: people, consent_version: view?.consent.version }),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) setError(typeof data?.detail === "string" ? data.detail : "Please check the form and try again.");
      else setState("sent");
    } catch { setError("No connection. Please try again."); }
    finally { setBusy(false); }
  };

  const word = view?.file_word ?? "trip";
  const who = word === "trip" ? "travelling" : "staying";
  return (
    <main className="min-h-screen bg-[var(--haip-canvas)] px-4 py-6">
      <div className="mx-auto flex w-full max-w-lg flex-col gap-4">
        {state === "loading" && <p className="text-[15px] text-[var(--haip-fg-subtle)]">Loading…</p>}
        {state === "bad" && <Card><EmptyState title="This link does not work" hint="Please ask us for a new link on WhatsApp." /></Card>}
        {state === "sent" && <Card><EmptyState title="Thank you" hint={`We have your details. See you on the ${word}!`} /></Card>}
        {state === "ready" && view && (
          <form className="flex flex-col gap-4" onSubmit={e => { e.preventDefault(); submit(); }}>
            <header>
              <h1 className="font-[family-name:var(--font-display)] text-[24px] font-semibold">Hello {view.guest_first_name}</h1>
              <p className="mt-1 text-[15px] text-[var(--haip-fg-muted)]">
                Your {word}{view.place ? ` at ${view.place}` : ""}, {day(view.check_in)} – {day(view.check_out)}. Please fill this in for
                everyone {who} (about 2 minutes, a little longer for guests from abroad).
              </p>
            </header>
            {people.map((p, i) => {
              const abroad = p.nationality !== "IN";
              const free = view.no_visa_needed.includes(p.nationality);
              const oci = p.visa_type === "oci";
              return (
                <Card key={i}>
                  <CardHeader title={`Guest ${i + 1}`} tone="plain" />
                  <CardBody className="flex flex-col gap-3 px-4 pb-4">
                    <label className={lbl}>Full name (as on the ID)<input className={field} value={p.name} onChange={person(i, "name")} autoComplete="off" /></label>
                    <label className={lbl}>Age<input className={field} inputMode="numeric" pattern="[0-9]*" value={p.age} onChange={person(i, "age")} /></label>
                    <label className={lbl}>Nationality
                      <select className={field} value={p.nationality} onChange={person(i, "nationality")}>
                        {p.nationality === "" && <option value="">Choose</option>}
                        <option value="IN">India</option>
                        {countries.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
                      </select>
                    </label>
                    {(!abroad || (free && !p.passport_number)) && (
                      <>
                        <label className={lbl}>ID type
                          <select className={field} value={p.id_type} onChange={person(i, "id_type")}>
                            {view.id_types.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
                          </select>
                        </label>
                        <label className={lbl}>ID number
                          <input className={field} value={p.id_number} onChange={person(i, "id_number")} autoComplete="off"
                            inputMode={p.id_type === "aadhaar" ? "numeric" : "text"} />
                          {p.id_type === "aadhaar" && <span className={hint}>We keep only the last 4 digits.</span>}
                        </label>
                      </>
                    )}
                    {abroad && p.nationality !== "" && (
                      <fieldset className="flex flex-col gap-3 rounded-xl border border-[var(--haip-border)] p-3">
                        <legend className="px-1 text-[14px] font-semibold">Passport and visa</legend>
                        <p className={hint}>
                          Indian law asks us to register guests who are not Indian citizens with the Bureau of Immigration
                          (Form C) within 24 hours of arrival. Your numbers are stored encrypted and seen only by the team member who files it.
                          {free ? " Citizens of Nepal and Bhutan need no visa; the passport is optional (give another ID above instead)." : ""}
                        </p>
                        <label className={lbl}>Passport number{free ? " (optional)" : ""}
                          <input className={field} value={p.passport_number} onChange={person(i, "passport_number")} autoComplete="off" autoCapitalize="characters" />
                        </label>
                        {(!free || p.passport_number) && (
                          <>
                            <label className={lbl}>Passport expiry date<input type="date" className={field} value={p.passport_expires_on} onChange={person(i, "passport_expires_on")} /></label>
                            <PhotoField url={url} kind="passport" label="Photo of the passport page with your photo" value={p.passport_photo_id}
                              onDone={id => set(i, "passport_photo_id", id)} />
                          </>
                        )}
                        <label className={lbl}>Visa type{free ? " (optional)" : ""}
                          <select className={field} value={p.visa_type} onChange={person(i, "visa_type")}>
                            <option value="">{free ? "No visa" : "Choose"}</option>
                            {view.visa_types.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
                          </select>
                        </label>
                        {p.visa_type && (
                          <>
                            <label className={lbl}>{oci ? "OCI card number" : "Visa number"}
                              <input className={field} value={p.visa_number} onChange={person(i, "visa_number")} autoComplete="off" autoCapitalize="characters" />
                            </label>
                            {!oci && <label className={lbl}>Visa expiry date<input type="date" className={field} value={p.visa_expires_on} onChange={person(i, "visa_expires_on")} /></label>}
                            <PhotoField url={url} kind="visa" label={oci ? "Photo of the OCI card" : "Photo of the visa"} value={p.visa_photo_id}
                              onDone={id => set(i, "visa_photo_id", id)} />
                          </>
                        )}
                        <label className={lbl}>Date you arrived in India<input type="date" className={field} value={p.arrived_india_on} onChange={person(i, "arrived_india_on")} /></label>
                        <label className={lbl}>Arrived in India from (city, country)<input className={field} value={p.arrived_from} onChange={person(i, "arrived_from")} /></label>
                        <label className={lbl}>Where you go after this {word} (city, country)<input className={field} value={p.onward_to} onChange={person(i, "onward_to")} /></label>
                      </fieldset>
                    )}
                  </CardBody>
                </Card>
              );
            })}
            <Card>
              <CardHeader title="Emergency contact and wishes" tone="plain" />
              <CardBody className="flex flex-col gap-3 px-4 pb-4">
                <label className={lbl}>Emergency contact name<input className={field} value={f.emergency_name} onChange={e => setF({ ...f, emergency_name: e.target.value })} /></label>
                <label className={lbl}>Emergency contact phone<input className={field} type="tel" inputMode="tel" value={f.emergency_phone}
                  onChange={e => setF({ ...f, emergency_phone: e.target.value })} /></label>
                <label className={lbl}>Food: allergies or preferences (optional)<input className={field} value={f.food} onChange={e => setF({ ...f, food: e.target.value })} /></label>
                <label className={lbl}>Anything else we should know (optional)
                  <textarea className={`${field} min-h-24 py-2`} value={f.requests} onChange={e => setF({ ...f, requests: e.target.value })} />
                </label>
              </CardBody>
            </Card>
            <Card>
              <CardBody className="flex flex-col gap-3 p-4">
                <label className="flex items-start gap-3 text-[15px]">
                  <input type="checkbox" className="mt-1 size-5 shrink-0" checked={f.agreed} onChange={e => setF({ ...f, agreed: e.target.checked })} />
                  <span>{view.consent.text}</span>
                </label>
                <label className={lbl}>Type your full name to sign<input className={field} value={f.signed_name} onChange={e => setF({ ...f, signed_name: e.target.value })} /></label>
              </CardBody>
            </Card>
            {error && <p role="alert" className="rounded-xl bg-[var(--haip-status-danger-bg)] px-3 py-2 text-[14.5px] text-[var(--haip-status-danger-fg)]">{error}</p>}
            <button type="submit" disabled={busy} className="haip-btn-primary min-h-12 text-[16px]">{busy ? "Sending…" : "Send my details"}</button>
          </form>
        )}
      </div>
    </main>
  );
}
