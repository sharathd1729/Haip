// Calendar holds as the Calendar (timeline + phone month grid) and the Bookings strip show them: ONE set of rules.
// - A Google Calendar event entered one night at a time arrives as several holds: back-to-back holds with the same label are
//   drawn as one bar (mergeHolds).
// - An event that names no unit is held on EVERY unit ("Which villa?"). It is shown once, in its own row, and the unit rows
//   only get a faint stripe on those days (splitWaiting). The API marks it with event.needs_vehicle and shares one
//   event.event_key across its copies.
// - Labels lose the bold/italic markers people type in Google ("*Mr.Saksham*"), as the backend's clean_name does.

export interface HoldEvent {
  title: string | null;
  needs_vehicle: boolean;
  event_key?: string;
  feed_name?: string | null;
  dates_source?: string;
  details: { guest_name?: string; phone?: string; destination?: string; package?: string; guests?: string; amounts?: Record<string, number> };
}
export interface HoldBlock { id: string; blocked_from: string; blocked_to: string; reason: string; notes?: string | null; vehicle?: string; event?: HoldEvent | null }

/** "*Mr.Saksham*" -> "Mr.Saksham", "*Ms. Ritika* / _Mr. Rahul_" -> "Ms. Ritika / Mr. Rahul"; separators keep their spacing. */
export function cleanName(value: string | null | undefined): string {
  return (value ?? "").split(/(\s*\/\s*)/).map((p, i) => (i % 2 ? p : p.trim().replace(/^[*_]+|[*_]+$/g, "").trim())).join("").trim();
}

export const isWaiting = (b: Pick<HoldBlock, "event">) => !!b.event?.needs_vehicle;

/** What a hold says on its bar: the guest or event for a calendar hold, else what kind of hold it is. */
export function holdLabel(b: Pick<HoldBlock, "event" | "reason">): string {
  if (b.event) return cleanName(b.event.details?.guest_name || b.event.title) || "Calendar hold";
  if (b.reason === "maintenance") return "Maintenance";
  return b.reason === "owner_use" || b.reason === "personal" ? "Owner use" : "Blocked";
}

const nights = (from: string, to: string) => Math.max(1, Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 86_400_000));
export const nightsWord = (from: string, to: string) => { const n = nights(from, to); return `${n} night${n === 1 ? "" : "s"}`; };

/** Back-to-back holds (one ends the day the next starts) with the same label, kind and waiting state become one. The first hold
 *  keeps its id and event (it is what a tap opens); ``ids`` lists every hold folded in. Input order does not matter. */
export function mergeHolds<T extends HoldBlock>(holds: T[]): (T & { ids: string[] })[] {
  const sorted = [...holds].sort((a, b) => a.blocked_from.localeCompare(b.blocked_from) || a.blocked_to.localeCompare(b.blocked_to));
  const out: (T & { ids: string[] })[] = [];
  for (const h of sorted) {
    const last = out[out.length - 1];
    if (last && last.blocked_to >= h.blocked_from && holdLabel(last) === holdLabel(h) && last.reason === h.reason
        && isWaiting(last) === isWaiting(h) && (last.vehicle ?? "") === (h.vehicle ?? "")) {
      if (h.blocked_to > last.blocked_to) last.blocked_to = h.blocked_to;
      last.ids.push(h.id);
    } else {
      out.push({ ...h, ids: [h.id] });
    }
  }
  return out;
}

/** Waiting ("Which villa?") holds once each, merged, plus every row's own holds without them, merged. */
export function splitWaiting<R extends { blocks: HoldBlock[] }>(rows: R[]): { waiting: (HoldBlock & { ids: string[] })[]; rows: (R & { blocks: (HoldBlock & { ids: string[] })[] })[] } {
  const seen = new Map<string, HoldBlock>();
  for (const r of rows) for (const b of r.blocks) {
    if (!isWaiting(b)) continue;
    const key = b.event?.event_key ?? `${holdLabel(b)}|${b.blocked_from}|${b.blocked_to}`;
    if (!seen.has(key)) seen.set(key, { ...b, vehicle: undefined });
  }
  return {
    waiting: mergeHolds([...seen.values()]),
    rows: rows.map(r => ({ ...r, blocks: mergeHolds(r.blocks.filter(b => !isWaiting(b))) })),
  };
}
