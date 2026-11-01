"use client";
// The guest's private trip form (no login): names, ages and ID of everyone travelling, an emergency contact, food notes and
// requests, then a typed signature under the consent text of a stated version. Backend: GET/POST
// /api/v1/public/ops/guest-form/{token} (ops_guest_form; Aadhaar keeps only the last 4 digits). Phone first, 16px inputs.
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { Card, CardBody, CardHeader, EmptyState } from "@/components/ui/kit";

const _raw = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
const API = _raw.endsWith("/api/v1") ? _raw : `${_raw}/api/v1`;
const field = "min-h-12 w-full rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-[16px] text-[var(--haip-fg)]";
const lbl = "flex flex-col gap-1.5 text-[14px] font-semibold text-[var(--haip-fg)]";

interface View {
  guest_first_name: string; check_in: string; check_out: string; party: number; submitted: boolean;
  id_types: { value: string; label: string }[]; consent: { version: string; text: string };
}
interface Person { name: string; age: string; id_type: string; id_number: string }

const day = (iso: string) => new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "UTC" });

export default function GuestTripForm() {
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
      setPeople(Array.from({ length: v.party }, () => ({ name: "", age: "", id_type: "aadhaar", id_number: "" })));
      setState(v.submitted ? "sent" : "ready");
    }).catch(() => setState("bad"));
  }, [url]);

  const person = (i: number, k: keyof Person) => (e: { target: { value: string } }) =>
    setPeople(ps => ps.map((p, n) => (n === i ? { ...p, [k]: e.target.value } : p)));
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

  return (
    <main className="min-h-screen bg-[var(--haip-canvas)] px-4 py-6">
      <div className="mx-auto flex w-full max-w-lg flex-col gap-4">
        {state === "loading" && <p className="text-[15px] text-[var(--haip-fg-subtle)]">Loading…</p>}
        {state === "bad" && <Card><EmptyState title="This link does not work" hint="Please ask us for a new link on WhatsApp." /></Card>}
        {state === "sent" && <Card><EmptyState title="Thank you" hint="We have your details. See you on the trip!" /></Card>}
        {state === "ready" && view && (
          <form className="flex flex-col gap-4" onSubmit={e => { e.preventDefault(); submit(); }}>
            <header>
              <h1 className="font-[family-name:var(--font-display)] text-[24px] font-semibold">Hello {view.guest_first_name}</h1>
              <p className="mt-1 text-[15px] text-[var(--haip-fg-muted)]">
                Your trip {day(view.check_in)} – {day(view.check_out)}. Please fill this in for everyone travelling (about 2 minutes).
              </p>
            </header>
            {people.map((p, i) => (
              <Card key={i}>
                <CardHeader title={`Guest ${i + 1}`} tone="plain" />
                <CardBody className="flex flex-col gap-3 px-4 pb-4">
                  <label className={lbl}>Full name<input className={field} value={p.name} onChange={person(i, "name")} autoComplete="off" /></label>
                  <label className={lbl}>Age<input className={field} inputMode="numeric" pattern="[0-9]*" value={p.age} onChange={person(i, "age")} /></label>
                  <label className={lbl}>ID type
                    <select className={field} value={p.id_type} onChange={person(i, "id_type")}>
                      {view.id_types.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
                    </select>
                  </label>
                  <label className={lbl}>ID number
                    <input className={field} value={p.id_number} onChange={person(i, "id_number")} autoComplete="off"
                      inputMode={p.id_type === "aadhaar" ? "numeric" : "text"} />
                    {p.id_type === "aadhaar" && <span className="text-[13px] font-normal text-[var(--haip-fg-subtle)]">We keep only the last 4 digits.</span>}
                  </label>
                </CardBody>
              </Card>
            ))}
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
