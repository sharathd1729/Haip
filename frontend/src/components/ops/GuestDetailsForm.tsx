"use client";
// The guest's private details form (no login), for a caravan trip (/r/trip/<token>) or a villa stay (/r/stay/<token>).
// Workspace redesign Phase 4, direction A2 "one page": a branded header, then a checklist of parts (Guests, Emergency
// contact, Food and questions, Sign); the open part expands, a ticked part folds to a one-line summary. What is asked comes
// from the workspace's own form (brand_config.guest_form via the view's `form`): age / emergency / food / requests are
// off | ask | req and the owner's own questions follow; names, nationality, an ID each, passport + visa for Form C and the
// signature are always asked. Backend: GET/POST /api/v1/public/ops/guest-form/{token} + POST .../photo (ops_guest_form).
// Phone first, 16px inputs, 48px buttons.
import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { Card, EmptyState } from "@/components/ui/kit";
import { Check } from "@/lib/icons";
import { countryName } from "@/lib/ops";
import { PersonFields, blankPerson, field, hint, lbl, personDone, type Option, type Person } from "./guestform/PersonFields";

const _raw = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
const API = _raw.endsWith("/api/v1") ? _raw : `${_raw}/api/v1`;

type Mode = "off" | "ask" | "req";
interface Question { id: string; label: string; kind: "text" | "yesno" | "choice" | "date"; options: string[]; required: boolean }
interface FormCfg { age: Mode; emergency: Mode; food: Mode; requests: Mode; questions: Question[]; welcome: string; rules_url: string }
interface View {
  guest_first_name: string; check_in: string; check_out: string; party: number; submitted: boolean; business: string | null;
  file_word: "trip" | "stay"; unit_word: string; place: string | null; guest_from_abroad: boolean;
  id_types: Option[]; countries: string[]; no_visa_needed: string[]; visa_types: Option[];
  consent: { version: string; text: string }; form?: FormCfg;
}
type Part = "guests" | "emergency" | "wishes" | "sign";

const DEFAULT_FORM: FormCfg = { age: "ask", emergency: "req", food: "ask", requests: "ask", questions: [], welcome: "", rules_url: "" };
const day = (iso: string) => new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });
const pill = (on: boolean) => `min-h-11 rounded-full border px-4 text-[14px] ${on
  ? "border-primary bg-primary font-semibold text-primary-foreground" : "border-[var(--haip-border)] bg-[var(--haip-card)] text-[var(--haip-fg)]"}`;
const optional = (m: Mode) => (m === "ask" ? " (optional)" : "");

function Ring({ done, of }: { done: number; of: number }) {
  const c = 2 * Math.PI * 18;
  return (
    <svg width="48" height="48" viewBox="0 0 48 48" role="img" aria-label={`${done} of ${of} parts done`}>
      <circle cx="24" cy="24" r="18" fill="none" stroke="var(--haip-border)" strokeWidth="5" />
      <circle cx="24" cy="24" r="18" fill="none" stroke="var(--primary)" strokeWidth="5" strokeLinecap="round"
        strokeDasharray={`${(c * done) / Math.max(of, 1)} ${c}`} transform="rotate(-90 24 24)" />
      <text x="24" y="28" textAnchor="middle" fontSize="12" fontWeight="700" fill="var(--haip-fg)">{done}/{of}</text>
    </svg>
  );
}

function Section({ n, title, summary, done, open, onOpen, children }: {
  n: number; title: string; summary: string; done: boolean; open: boolean; onOpen: () => void; children: React.ReactNode;
}) {
  return (
    <section className={`overflow-hidden rounded-2xl border bg-[var(--haip-card)] ${open ? "border-primary" : "border-[var(--haip-border)]"}`}>
      <h2 className="m-0">
        <button type="button" onClick={onOpen} aria-expanded={open} className="flex min-h-14 w-full items-center gap-3 px-4 text-left">
          <span className={`flex size-7 shrink-0 items-center justify-center rounded-full text-[13px] font-bold ${done
            ? "bg-primary text-primary-foreground" : open ? "border-2 border-primary text-primary" : "border-2 border-[var(--haip-border-strong)] text-[var(--haip-fg-subtle)]"}`}>
            {done ? <Check size={15} aria-hidden /> : n}
          </span>
          <span className="flex-1 text-[16px] font-semibold text-[var(--haip-fg)]">{title}</span>
          {!open && summary && <span className="max-w-[45%] truncate text-[13px] text-[var(--haip-fg-subtle)]">{summary}</span>}
        </button>
      </h2>
      {open && <div className="flex flex-col gap-4 px-4 pb-4">{children}</div>}
    </section>
  );
}

export default function GuestDetailsForm() {
  const { token } = useParams<{ token: string }>();
  const url = `${API}/public/ops/guest-form/${encodeURIComponent(token)}`;
  const [view, setView] = useState<View | null>(null);
  const [state, setState] = useState<"loading" | "bad" | "ready" | "sent">("loading");
  const [people, setPeople] = useState<Person[]>([]);
  const [f, setF] = useState({ emergency_name: "", emergency_phone: "", food: "", requests: "", signed_name: "", agreed: false });
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [open, setOpen] = useState<Part>("guests");
  const [seen, setSeen] = useState<Part[]>([]);  // parts the guest moved on from: an all-optional part is ticked only then
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetch(url).then(async r => {
      if (!r.ok) { setState("bad"); return; }
      const v: View = await r.json();
      setView(v);
      // A website booking said the guest is from abroad: the first guest picks their nationality instead of "India".
      setPeople(Array.from({ length: v.party }, (_, i) => blankPerson(v.guest_from_abroad && i === 0 ? "" : "IN")));
      setState(v.submitted ? "sent" : "ready");
    }).catch(() => setState("bad"));
  }, [url]);

  const cfg = view?.form ?? DEFAULT_FORM;
  const countries = useMemo(() => (view?.countries ?? []).filter(c => c !== "IN")
    .map(c => ({ value: c, label: countryName(c) })).sort((a, b) => a.label.localeCompare(b.label)), [view]);
  const set = (i: number, k: keyof Person, v: string) => setPeople(ps => ps.map((p, n) => (n === i ? { ...p, [k]: v } : p)));
  const answer = (id: string, v: string) => setAnswers(a => ({ ...a, [id]: v }));

  const noVisa = view?.no_visa_needed ?? [];
  const guestsDone = people.length > 0 && people.every(p => personDone(p, cfg.age === "req", noVisa));
  const phoneOk = f.emergency_phone.replace(/\D/g, "").length >= 10;
  const emergencyDone = cfg.emergency === "req" ? !!f.emergency_name.trim() && phoneOk
    : !f.emergency_name.trim() && !f.emergency_phone.trim() ? seen.includes("emergency") : !!f.emergency_name.trim() && phoneOk;
  const hasWishes = cfg.food !== "off" || cfg.requests !== "off" || cfg.questions.length > 0;
  const wishesDone = (cfg.food !== "req" || !!f.food.trim()) && (cfg.requests !== "req" || !!f.requests.trim())
    && cfg.questions.every(q => !q.required || !!(answers[q.id] ?? "").trim())
    && (seen.includes("wishes") || !!f.food.trim() || !!f.requests.trim() || Object.values(answers).some(v => v.trim()));
  const signDone = f.agreed && !!f.signed_name.trim();
  const parts: { key: Part; done: boolean }[] = [
    { key: "guests", done: guestsDone },
    ...(cfg.emergency !== "off" ? [{ key: "emergency" as Part, done: emergencyDone }] : []),
    ...(hasWishes ? [{ key: "wishes" as Part, done: wishesDone }] : []),
    { key: "sign", done: signDone },
  ];
  const done = parts.filter(p => p.done).length;
  const next = (from: Part) => {
    setSeen(s => (s.includes(from) ? s : [...s, from]));
    setOpen(parts[Math.min(parts.findIndex(p => p.key === from) + 1, parts.length - 1)].key);
  };
  const numberOf = (k: Part) => parts.findIndex(p => p.key === k) + 1;

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const r = await fetch(url, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...f, guests: people, answers, consent_version: view?.consent.version }),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) setError(typeof data?.detail === "string" ? data.detail : "Please check the form and try again.");
      else setState("sent");
    } catch { setError("No connection. Please try again."); }
    finally { setBusy(false); }
  };

  const word = view?.file_word ?? "trip";
  const who = word === "trip" ? "travelling" : "staying";
  const firstNames = people.map(p => p.name.trim().split(" ")[0]).filter(Boolean);
  const cont = (k: Part) => (
    <button type="button" className="haip-btn-secondary min-h-12 text-[15px]" onClick={() => next(k)}>Save and continue</button>
  );

  return (
    <main className="min-h-screen bg-[var(--haip-canvas)]">
      {state === "loading" && <p className="px-4 py-6 text-[15px] text-[var(--haip-fg-subtle)]">Loading…</p>}
      {state === "bad" && <div className="mx-auto max-w-lg px-4 py-6"><Card><EmptyState title="This link does not work" hint="Please ask us for a new link on WhatsApp." /></Card></div>}
      {state === "sent" && <div className="mx-auto max-w-lg px-4 py-6"><Card><EmptyState title="Thank you" hint={`We have your details. See you on the ${word}!`} /></Card></div>}
      {state === "ready" && view && (
        <form className="flex flex-col" onSubmit={e => { e.preventDefault(); submit(); }}>
          <header className="bg-primary px-4 pb-8 pt-6 text-primary-foreground">
            <div className="mx-auto flex max-w-lg flex-col gap-1.5">
              <span className="text-[13px] opacity-85">{[view.business, view.place].filter(Boolean).join(" · ")}</span>
              <h1 className="font-[family-name:var(--font-display)] text-[26px] font-semibold leading-tight">Before you arrive, {view.guest_first_name}</h1>
              <span className="text-[14px] opacity-90">{day(view.check_in)} to {day(view.check_out)} · {view.party} {view.party === 1 ? "guest" : "guests"}</span>
              <span className="text-[14px] opacity-90">{cfg.welcome || `Please fill this in for everyone ${who}. About 3 minutes.`}</span>
            </div>
          </header>
          <div className="mx-auto -mt-4 flex w-full max-w-lg flex-col gap-3 px-4 pb-6">
            <div className="flex items-center gap-3 rounded-2xl border border-[var(--haip-border)] bg-[var(--haip-card)] px-4 py-3">
              <Ring done={done} of={parts.length} />
              <span className="flex-1 text-[14px] text-[var(--haip-fg-muted)]">
                {done === parts.length ? "All done. Send it when you are ready." : `${done} of ${parts.length} parts done.`}
              </span>
            </div>

            <Section n={numberOf("guests")} title="Guests" done={guestsDone} open={open === "guests"} onOpen={() => setOpen("guests")}
              summary={firstNames.length ? firstNames.join(", ") : `${people.length} to add`}>
              {people.map((p, i) => (
                <div key={i} className="flex flex-col gap-3 border-t border-[var(--haip-border)] pt-4 first:border-t-0 first:pt-0">
                  <span className="text-[13px] font-semibold uppercase tracking-wide text-[var(--haip-fg-subtle)]">Guest {i + 1}</span>
                  <PersonFields p={p} i={i} url={url} ask={cfg.age} idTypes={view.id_types} countries={countries} noVisa={noVisa}
                    visaTypes={view.visa_types} word={word} set={set} />
                </div>
              ))}
              {cont("guests")}
            </Section>

            {cfg.emergency !== "off" && (
              <Section n={numberOf("emergency")} title={`Emergency contact${optional(cfg.emergency)}`} done={emergencyDone}
                open={open === "emergency"} onOpen={() => setOpen("emergency")} summary={f.emergency_name.trim()}>
                <p className={hint}>Only used if something goes wrong during your {word}.</p>
                <label className={lbl}>Name<input className={field} value={f.emergency_name} onChange={e => setF({ ...f, emergency_name: e.target.value })} /></label>
                <label className={lbl}>Phone<input className={field} type="tel" inputMode="tel" value={f.emergency_phone}
                  onChange={e => setF({ ...f, emergency_phone: e.target.value })} /></label>
                {cont("emergency")}
              </Section>
            )}

            {hasWishes && (
              <Section n={numberOf("wishes")} title="Food and a few questions" done={wishesDone} open={open === "wishes"}
                onOpen={() => setOpen("wishes")} summary={f.food.trim()}>
                {cfg.food !== "off" && (
                  <label className={lbl}>Food: allergies or preferences{optional(cfg.food)}
                    <input className={field} value={f.food} onChange={e => setF({ ...f, food: e.target.value })} />
                  </label>
                )}
                {cfg.questions.map(q => (
                  <div key={q.id} className={lbl}>
                    <span id={`q-${q.id}`}>{q.label}{q.required ? "" : <span className={hint}> (optional)</span>}</span>
                    {q.kind === "text" && <input aria-labelledby={`q-${q.id}`} className={field} value={answers[q.id] ?? ""} onChange={e => answer(q.id, e.target.value)} />}
                    {q.kind === "date" && <input aria-labelledby={`q-${q.id}`} type="date" className={field} value={answers[q.id] ?? ""} onChange={e => answer(q.id, e.target.value)} />}
                    {(q.kind === "yesno" || q.kind === "choice") && (
                      <div role="radiogroup" aria-labelledby={`q-${q.id}`} className="flex flex-wrap gap-2">
                        {(q.kind === "yesno" ? ["Yes", "No"] : q.options).map(o => (
                          <button key={o} type="button" role="radio" aria-checked={answers[q.id] === o} className={pill(answers[q.id] === o)}
                            onClick={() => answer(q.id, o)}>{o}</button>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
                {cfg.requests !== "off" && (
                  <label className={lbl}>Anything we should arrange{optional(cfg.requests)}
                    <textarea className={`${field} min-h-24 py-2`} value={f.requests} onChange={e => setF({ ...f, requests: e.target.value })} />
                  </label>
                )}
                {cont("wishes")}
              </Section>
            )}

            <Section n={numberOf("sign")} title="Check and sign" done={signDone} open={open === "sign"} onOpen={() => setOpen("sign")}
              summary={f.signed_name.trim()}>
              <label className="flex items-start gap-3 text-[15px] text-[var(--haip-fg)]">
                <input type="checkbox" className="mt-1 size-5 shrink-0 accent-[var(--primary)]" checked={f.agreed} onChange={e => setF({ ...f, agreed: e.target.checked })} />
                <span>{view.consent.text}{cfg.rules_url && <> <a href={cfg.rules_url} target="_blank" rel="noopener noreferrer" className="font-semibold text-primary underline">Read the house rules</a></>}</span>
              </label>
              <label className={lbl}>Type your full name to sign<input className={field} value={f.signed_name} onChange={e => setF({ ...f, signed_name: e.target.value })} /></label>
            </Section>

            {error && <p role="alert" className="rounded-xl bg-[var(--haip-status-danger-bg)] px-3 py-2 text-[14.5px] text-[var(--haip-status-danger-fg)]">{error}</p>}
            <button type="submit" disabled={busy} className="haip-btn-primary min-h-12 text-[16px]">{busy ? "Sending…" : "Send my details"}</button>
          </div>
        </form>
      )}
    </main>
  );
}
