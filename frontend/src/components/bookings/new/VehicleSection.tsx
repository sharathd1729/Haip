"use client";
// 3 Caravan and interior: "First free caravan" (default) or a named one, each Vacant / Tight / Booked for the chosen dates AND
// times (the server's rule); the interior (Black / White) and staff notes go to the booking's staff notes.
import { BTN, Chip, Field, INPUT } from "@/components/quotes/ui";
import { StatusPill } from "@/components/ui/kit";
import { clock, day } from "./helpers";
import type { BookingForm, ComposeSetup, Preview } from "./types";
import { HINT, Note, Opt } from "./ui";

const PILL = { free: ["success", "Vacant"], tight: ["warning", "Tight"], booked: ["danger", "Booked"] } as const;

export function VehicleSection({ form, set, setup, preview }: {
  form: BookingForm; set: (patch: Partial<BookingForm>) => void; setup: ComposeSetup; preview: Preview | undefined;
}) {
  const v = preview?.vehicles ?? null;
  const rows = v?.vehicles ?? [];
  const chosen = form.vehicle === "auto" ? null : rows.find(r => r.property_id === form.vehicle) ?? null;
  const holding = preview?.vehicle ?? null;
  const holdingRow = holding ? rows.find(r => r.property_id === holding.property_id) : null;
  return (
    <>
      {!v && <p className={HINT}>Pick the dates and times first. HAIP then shows which caravan is free.</p>}
      <div className="grid gap-2" role="radiogroup" aria-label="Caravan">
        <Opt on={form.vehicle === "auto"} onClick={() => set({ vehicle: "auto" })} title="First free caravan"
          sub={v ? (v.auto ? `${v.auto.name} will be held for these dates` : "None free on these dates")
            : `${setup.vehicles.map(x => x.name).join(", or ")} if the first is taken`}
          right={v?.auto ? <StatusPill tone="success">{v.auto.name}</StatusPill> : undefined} />
        {setup.vehicles.map(x => {
          const r = rows.find(row => row.property_id === x.id);
          const [tone, word] = r ? PILL[r.state] : (["neutral", "Pick dates"] as const);
          const label = !r ? x.name : r.state === "free" ? `${x.name} · Vacant` : r.state === "tight" ? `${x.name} · Vacant, tight turnaround`
            : `${x.name} · Booked`;
          const o = r?.other;
          return (
            <Opt key={x.id} on={form.vehicle === x.id} onClick={() => set({ vehicle: x.id })} title={label} testId={`veh-${x.name}`}
              sub={o && o.type === "booking" ? `${o.guest ?? "Another guest"} · ${day(o.from)} ${clock(o.from_time)} → ${day(o.to)} ${clock(o.to_time)}` : undefined}
              right={<StatusPill tone={tone}>{word}</StatusPill>} />
          );
        })}
      </div>
      {chosen?.state === "booked" && chosen.message && (
        <Note tone="bad" actions={<>
          {rows.filter(r => r.property_id !== chosen.property_id && r.state !== "booked").map(r => (
            <button key={r.property_id} type="button" className={BTN} onClick={() => set({ vehicle: r.property_id })}>Use {r.name}</button>
          ))}
          <button type="button" className={BTN} onClick={() => set({ vehicle: "auto" })}>First free</button>
        </>}>
          <span data-testid="clash-message">{chosen.message}</span>
        </Note>
      )}
      {form.vehicle === "auto" && v && !v.auto && v.message && <Note tone="bad"><span data-testid="clash-message">{v.message}</span></Note>}
      {holdingRow?.state === "tight" && holdingRow.message && <Note tone="warn">{holdingRow.message} Tell ops, or move the pickup later.</Note>}
      <div className="grid gap-1">
        <span className="text-xs font-semibold text-[var(--haip-fg-2)]">Interior</span>
        <div className="flex flex-wrap gap-1.5">
          {(["Black", "White", ""] as const).map(x => (
            <Chip key={x || "none"} on={form.interior === x} onClick={() => set({ interior: x })}>
              {x && <span aria-hidden className={x === "Black" ? "size-3.5 rounded border border-[var(--haip-border-strong)] bg-black" : "size-3.5 rounded border border-[var(--haip-border-strong)] bg-white"} />}
              {x || "Not decided"}
            </Chip>
          ))}
        </div>
      </div>
      <Field label="Staff notes (team only)" htmlFor="nb-notes">
        <textarea id="nb-notes" className={`${INPUT} min-h-[72px] py-2`} rows={2} maxLength={2000} value={form.notes}
          placeholder="Anything ops should know: occasion, food, early start" onChange={e => set({ notes: e.target.value })} />
      </Field>
      {preview?.staff_notes && <p className={HINT}>Saved in staff notes as: “{preview.staff_notes}”</p>}
    </>
  );
}
