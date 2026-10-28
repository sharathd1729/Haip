"use client";
// The villa stay file's own forms (ops_stays.py), each in a bottom sheet: the people (caretaker, cook, cleaner), Check in
// (keys + deposit), one meal, and the deposit decision. The shared sheets (checklist item, expense, extra) stay in
// TripSheets. Inputs are 16px+, buttons 48px+. The server checks every rule again; its message is shown when it says no.
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { FOOD_LABELS, rupees, type OpsFileFull } from "@/lib/ops";
import { Shell, input, label } from "./TripSheets";

export type StaySheetKind = "people" | "checkin" | "meal" | "deposit" | null;
type Submit = (path: string, body?: object, method?: "post" | "put" | "delete") => Promise<boolean>;

const ROLES = [
  { key: "caretaker", label: "Caretaker", duty: "caretaker" },
  { key: "cook", label: "Cook", duty: "fnb" },
  { key: "cleaner", label: "Cleaner", duty: "housekeeping" },
] as const;

export function StaySheets({ file, kind, onClose, submit, busy }: {
  file: OpsFileFull; kind: StaySheetKind; onClose: () => void; submit: Submit; busy: boolean;
}) {
  const d = file.details, s = file.stay, dep = file.account.deposit;
  const base = `/ops/files/${file.id}`;
  const [f, setF] = useState<Record<string, string>>({});
  const set = (k: string) => (e: { target: { value: string } }) => setF(p => ({ ...p, [k]: e.target.value }));

  // Fresh values each time a sheet opens; a background refetch must not wipe what the person is typing.
  useEffect(() => {
    if (kind === "people") setF({ caretaker: d.caretaker_staff_id ?? "", cook: d.cook_staff_id ?? "", cleaner: d.cleaner_staff_id ?? "" });
    else if (kind === "checkin") setF({ keys: "yes", deposit: dep && dep.status !== "pending" ? "yes" : dep ? "yes" : "no", amount: "", note: "" });
    else if (kind === "meal") setF({ date: s.check_in.slice(0, 10), meal: "dinner", guests: String(s.adults + s.children), food: "veg", notes: "" });
    else if (kind === "deposit") setF({ decision: "refund", amount: "", reason: "" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, file.id]);

  const staff = useQuery<{ id: string; name: string; active: boolean; duties?: { duty: string }[] }[]>({
    queryKey: ["ops-staff"], queryFn: () => api.get("/ops/staff").then(r => r.data), enabled: kind === "people", staleTime: 60_000,
  });
  const done = async (ok: Promise<boolean>) => { if (await ok) onClose(); };
  const num = (v: string) => (v.trim() === "" ? undefined : Number(v));
  const days: string[] = [];
  for (let t = new Date(`${s.check_in.slice(0, 10)}T00:00:00Z`); t <= new Date(`${s.check_out.slice(0, 10)}T00:00:00Z`); t.setUTCDate(t.getUTCDate() + 1)) {
    days.push(t.toISOString().slice(0, 10));
  }
  const red = (file.inspection ?? []).filter(i => i.status === "red").map(i => i.label);

  return (
    <>
      <Shell open={kind === "people"} onClose={onClose} title="Who looks after this stay" busy={busy} submitLabel="Save"
        description="They get their work on WhatsApp and send photos back. They never log in."
        onSubmit={() => done(submit(`${base}/people`, {
          caretaker_staff_id: f.caretaker || null, cook_staff_id: f.cook || null, cleaner_staff_id: f.cleaner || null,
        }))}>
        {ROLES.map(r => (
          <label key={r.key} className={label}>{r.label}
            <select className={input} value={f[r.key] ?? ""} onChange={set(r.key)}>
              <option value="">Nobody</option>
              {(staff.data ?? []).filter(p => p.active).map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </label>
        ))}
        {staff.data?.length === 0 && <p className="text-[13.5px] text-[var(--haip-fg-subtle)]">Add your caretaker, cook and cleaner on Ops → Staff first.</p>}
      </Shell>

      <Shell open={kind === "checkin"} onClose={onClose} title="Check in the guest" busy={busy} submitLabel="Guest is in"
        description="This tap starts the stay. Hand over the keys and collect the security deposit first."
        onSubmit={() => done(submit(`${base}/check-in`, {
          keys_handed: f.keys === "yes", deposit_collected: f.deposit === "yes",
          deposit_amount: !dep && f.deposit === "yes" ? num(f.amount ?? "") : undefined, note: f.note || undefined,
        }))}>
        <label className={label}>Keys handed over?
          <select className={input} value={f.keys ?? "yes"} onChange={set("keys")}><option value="yes">Yes</option><option value="no">Not yet</option></select>
        </label>
        <label className={label}>Security deposit {dep ? `(${rupees(dep.amount)} on the booking)` : ""}
          <select className={input} value={f.deposit ?? "no"} onChange={set("deposit")}>
            <option value="yes">Collected</option><option value="no">Not collected</option>
          </select>
        </label>
        {!dep && f.deposit === "yes" && (
          <label className={label}>Deposit amount (₹)<input className={input} required inputMode="decimal" value={f.amount ?? ""} onChange={set("amount")} /></label>
        )}
        <label className={label}>Note (optional)<input className={input} value={f.note ?? ""} onChange={set("note")} placeholder="Early arrival, 2 extra mattresses" /></label>
      </Shell>

      <Shell open={kind === "meal"} onClose={onClose} title="Add a meal" busy={busy} submitLabel="Add meal"
        description="The cook gets the plan on WhatsApp and replies OK."
        onSubmit={() => done(submit(`${base}/meals`, {
          date: f.date, meal: f.meal, guests: num(f.guests ?? ""), food: f.food, notes: f.notes || undefined,
        }))}>
        <label className={label}>Day
          <select className={input} value={f.date ?? ""} onChange={set("date")}>
            {days.map(x => <option key={x} value={x}>{new Date(`${x}T00:00:00Z`).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" })}</option>)}
          </select>
        </label>
        <label className={label}>Meal
          <select className={input} value={f.meal ?? "dinner"} onChange={set("meal")}>
            <option value="breakfast">Breakfast</option><option value="lunch">Lunch</option><option value="dinner">Dinner</option>
          </select>
        </label>
        <label className={label}>Guests eating<input className={input} required inputMode="numeric" pattern="[0-9]*" value={f.guests ?? ""} onChange={set("guests")} /></label>
        <label className={label}>Food
          <select className={input} value={f.food ?? "veg"} onChange={set("food")}>
            {Object.entries(FOOD_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <label className={label}>Notes (optional)<input className={input} value={f.notes ?? ""} onChange={set("notes")} placeholder="No onion, one child" /></label>
      </Shell>

      <Shell open={kind === "deposit"} onClose={onClose} title="Security deposit" busy={busy} submitLabel="Save decision"
        description={dep ? `${rupees(dep.amount)} held. Refund it in full, or keep part of it for damage.` : undefined}
        onSubmit={() => done(submit(`${base}/deposit`, f.decision === "refund" ? { decision: "refund" }
          : { decision: "deduct", amount: num(f.amount ?? ""), reason: f.reason }))}>
        <label className={label}>Decision
          <select className={input} value={f.decision ?? "refund"} onChange={set("decision")}>
            <option value="refund">Refund in full</option><option value="deduct">Keep part of it</option>
          </select>
        </label>
        {f.decision === "deduct" && (
          <>
            <label className={label}>Amount kept (₹)<input className={input} required inputMode="decimal" value={f.amount ?? ""} onChange={set("amount")} /></label>
            <label className={label}>Reason<input className={input} required value={f.reason ?? ""} onChange={set("reason")} placeholder="Broken lamp in bedroom 2" /></label>
            <p className="text-[13.5px] text-[var(--haip-fg-subtle)]">
              {red.length ? `The inspection photos of ${red.join(", ")} are kept with this decision.` : "The inspection found no problem. Write the reason clearly."}
            </p>
          </>
        )}
      </Shell>
    </>
  );
}
