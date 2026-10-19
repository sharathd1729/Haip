"use client";
// 2 Trip: package (by route: same price on both caravans) or custom trip, check-in/out dates and pickup/return times, nights
// worked out from the dates, day trip, guests, pickup point.
import { BTN, Field, INPUT, Stepper } from "@/components/quotes/ui";
import { StatusPill } from "@/components/ui/kit";
import { cn } from "@/lib/utils";
import { addDays, clock, cleanNumber, money, nightsBetween, packageLength } from "./helpers";
import type { BookingForm, ComposeSetup } from "./types";
import { HINT } from "./ui";

const PICKUPS = ["Koramangala", "HSR Layout", "Indiranagar", "Hebbal", "Whitefield", "Jakkur"];

export function TripSection({ form, set, setup }: { form: BookingForm; set: (patch: Partial<BookingForm>) => void; setup: ComposeSetup }) {
  const pkg = setup.packages.find(p => p.key === form.packageKey);
  const dayTrip = !!form.checkIn && form.checkOut === form.checkIn;
  const n = nightsBetween(form.checkIn, form.checkOut);
  const len = !form.checkIn || !form.checkOut || form.checkOut < form.checkIn ? ""
    : dayTrip ? `Day trip · ${clock(form.checkInTime)} → ${clock(form.checkOutTime)}`
      : `${n} night${n > 1 ? "s" : ""} · charged as ${Math.max(1, n)} day${n > 1 ? "s" : ""} on per-day packages`;
  const pickPackage = (key: string) => {
    if (key === "__custom") return set({ mode: "custom" });
    const p = setup.packages.find(x => x.key === key);
    const patch: Partial<BookingForm> = { mode: "fixed", packageKey: key };
    if (p && form.checkIn) Object.assign(patch, packageLength(p, form.checkIn, form));
    set(patch);
  };
  // A package that says how long it is sets check-out when check-in changes too; editing the dates afterwards is allowed
  // (the server then warns "usually N nights").
  const setCheckIn = (v: string) => {
    if (!v) return set({ checkIn: v });
    if (form.mode === "fixed" && pkg && (pkg.nights != null || pkg.product === "same_day")) return set({ checkIn: v, ...packageLength(pkg, v, form) });
    const keep = form.checkIn && form.checkOut && form.checkOut >= form.checkIn ? n : null;
    set({ checkIn: v, checkOut: keep !== null ? addDays(v, keep) : !form.checkOut || form.checkOut < v ? addDays(v, 1) : form.checkOut });
  };
  const free = form.mode === "custom" ? setup.custom.free_guests : pkg?.free_guests;
  return (
    <>
      <Field label="Package or route" htmlFor="nb-pkg">
        <select id="nb-pkg" className={INPUT} value={form.mode === "custom" ? "__custom" : form.packageKey} onChange={e => pickPackage(e.target.value)}>
          <option value="">Pick a package</option>
          {setup.packages.map(p => <option key={p.key} value={p.key}>{p.name} · {p.basis === "per_day" ? `${money(p.price)} a day` : money(p.price)}</option>)}
          <option value="__custom">Custom trip</option>
        </select>
      </Field>
      {form.mode === "fixed" && <p className={HINT}>Same price on both caravans. HAIP holds whichever one is free.</p>}
      {form.mode === "custom" && (
        <>
          <div className="grid grid-cols-2 gap-2.5">
            <Field label="Trip name" htmlFor="nb-ctitle">
              <input id="nb-ctitle" className={INPUT} maxLength={120} value={form.customTitle} onChange={e => set({ customTitle: e.target.value })} />
            </Field>
            <Field label="Rate per day (₹)" htmlFor="nb-crate">
              <input id="nb-crate" className={cn(INPUT, "num")} inputMode="numeric" value={form.ratePerDay} onChange={e => set({ ratePerDay: cleanNumber(e.target.value) })} />
            </Field>
          </div>
          <p className={HINT}>
            {Number(setup.custom.included_km_per_day)} km a day and {setup.custom.free_guests} guests are included. Extra guests {money(setup.custom.extra_guest_per_day)} each {setup.custom.extra_guest_unit === "trip" ? "per trip" : "a day"}.
          </p>
        </>
      )}
      <div className="grid grid-cols-2 gap-2.5">
        <Field label="Check-in date" htmlFor="nb-ci">
          <input id="nb-ci" type="date" className={INPUT} min={setup.today} value={form.checkIn} onChange={e => setCheckIn(e.target.value)} />
        </Field>
        <Field label="Pickup time" htmlFor="nb-cit">
          <input id="nb-cit" type="time" step={900} className={INPUT} value={form.checkInTime} onChange={e => set({ checkInTime: e.target.value })} />
        </Field>
        <Field label="Check-out date" htmlFor="nb-co">
          <input id="nb-co" type="date" className={INPUT} min={form.checkIn || setup.today} value={form.checkOut} onChange={e => set({ checkOut: e.target.value })} />
        </Field>
        <Field label="Return time" htmlFor="nb-cot">
          <input id="nb-cot" type="time" step={900} className={INPUT} value={form.checkOutTime} onChange={e => set({ checkOutTime: e.target.value })} />
        </Field>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {len ? <StatusPill tone="info">{len}</StatusPill> : <span className={HINT}>Nights are worked out from the dates.</span>}
        {form.checkIn && !dayTrip && (
          <button type="button" className={BTN} onClick={() => set({ checkOut: form.checkIn, ...(form.checkOutTime <= form.checkInTime ? { checkInTime: "10:00", checkOutTime: "20:00" } : {}) })}>
            Make it a day trip
          </button>
        )}
      </div>
      <div className="grid grid-cols-2 items-end gap-2.5">
        <Stepper id="nb-guests" label="Guests" value={form.guests} min={1} max={50} onChange={v => set({ guests: v })} />
        <span className={HINT}>{free ? `${free} included. Extra guests are charged per the package.` : "Adults and children together."}</span>
      </div>
      <Field label="Pickup point" htmlFor="nb-pickup">
        <input id="nb-pickup" className={INPUT} list="nb-pickups" placeholder="Area or landmark" value={form.pickup} maxLength={200}
          onChange={e => set({ pickup: e.target.value })} />
      </Field>
      <datalist id="nb-pickups">{PICKUPS.map(p => <option key={p} value={p} />)}</datalist>
    </>
  );
}
