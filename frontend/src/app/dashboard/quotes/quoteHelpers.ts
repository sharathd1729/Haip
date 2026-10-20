// Pure helpers for the quote builder: formatting, request payloads, the fallback option, refusal fixes and the route editor.
// No prices are computed here; the server prices every option (backend/app/services/package_pricing_service.py).
import { formatINR } from "@/lib/utils";
import type { Catalog, CatalogEntry, CatalogRecord, Json, KmDetail, OptionForm, ResellerTier, RouteForm } from "./types";

/** "89880.00" -> "₹89,880" (lakh grouping). */
export function money(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? formatINR(n) : "—";
}

export function kmText(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === "") return "—";
  return `${Math.round(Number(v)).toLocaleString("en-IN")} km`;
}

/** "2026-10-30" -> "Fri, 30 Oct" (a calendar date, so no time-zone shift). */
export function dayLabel(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(`${iso.slice(0, 10)}T00:00:00Z`);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });
}

export function addDays(iso: string, n: number): string {
  const d = new Date(`${iso.slice(0, 10)}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

export const entryData = (e: CatalogEntry): Json => (e.live?.data ?? e.draft?.data ?? {}) as Json;
export const entryName = (e: CatalogEntry): string => String(entryData(e).name ?? e.key);

/** published | new (never published, waiting approval) | change (a new version waiting approval). */
export function entryState(e: CatalogEntry): "published" | "new" | "change" {
  if (!e.live) return "new";
  return e.draft ? "change" : "published";
}

/** May this person approve this draft? Owners always; other publishers only someone else's draft (the server re-checks edits). */
export function canApprove(draft: CatalogRecord | null, perms: Catalog["permissions"]): boolean {
  if (!draft || !perms.can_publish) return false;
  return perms.is_owner || draft.created_by !== perms.user_id;
}

type Rate = { amount?: string; unit?: string; level?: string | null; label?: string };

export function packageLevels(data: Json): string[] {
  const rates = (data.rates as Rate[] | undefined) ?? [];
  const levels = Array.from(new Set(rates.map(r => r.level).filter((l): l is string => !!l)));
  return levels.sort((a, b) => (Number(a) - Number(b)) || a.localeCompare(b));
}

/** One line for a plan card: "₹70,000 + tax", "₹25,000 a day + tax", "₹35,000-₹45,000 a day + tax". */
export function packageTag(data: Json): string {
  const rates = (data.rates as Rate[] | undefined) ?? [];
  if (!rates.length) return "No price set";
  const unit = rates[0].unit ?? "package";
  const amounts = rates.map(r => Number(r.amount ?? 0)).filter(Number.isFinite);
  const lo = Math.min(...amounts), hi = Math.max(...amounts);
  const each = unit === "day" ? " a day" : unit === "night" ? " a night" : "";
  const price = lo === hi ? money(lo) : `${money(lo)}-${money(hi)}`;
  return `${price}${each} + tax`;
}

type Stop = { name?: string; order?: number; distance_km_from_previous?: string | number | null; overnight?: boolean };

/** Kilometres of a route's stops, or null when a stop has no distance. */
export function routeKm(data: Json): number | null {
  const stops = (data.stops as Stop[] | undefined) ?? [];
  if (!stops.length || stops.some(s => s.distance_km_from_previous === null || s.distance_km_from_previous === undefined)) return null;
  return stops.reduce((sum, s) => sum + Number(s.distance_km_from_previous), 0);
}

export function routeStops(data: Json): Stop[] {
  return [...((data.stops as Stop[] | undefined) ?? [])].sort((a, b) => (a.order ?? 0) - (b.order ?? 0));
}

export function routeSights(data: Json): { name: string; km_round_trip: string | number }[] {
  return (data.sights as { name: string; km_round_trip: string | number }[] | undefined) ?? [];
}

/** The JSON body for one option: empty choices are left out so the server applies the published defaults. */
export function toOptionPayload(o: OptionForm): Json {
  const out: Json = { package_key: o.package_key, start_date: o.start_date, nights: o.nights, adults: o.adults, children: o.children,
    sights: o.sights, kits: o.kits, extra_hours: o.extra_hours, channel: o.channel };
  if (o.level) out.level = o.level;
  if (o.destination_key) out.destination_key = o.destination_key;
  if (o.km_rate) out.km_rate = o.km_rate;
  if (o.discount_percent && Number(o.discount_percent) > 0) out.discount_percent = o.discount_percent;
  if (o.vehicle_property_id) out.vehicle_property_id = o.vehicle_property_id;
  if (o.channel === "reseller") {
    if (o.reseller_tier) out.reseller_tier = o.reseller_tier;
    if (o.commission_percent) out.commission_percent = o.commission_percent;
  }
  return out;
}

const pkgData = (c: Catalog, key: string): Json | null => {
  const e = c.packages.find(p => p.key === key);
  return e ? entryData(e) : null;
};

export function kitsFor(c: Catalog, packageKey: string) {
  return c.kits.filter(k => k.package_keys.includes(packageKey));
}

/** The fallback option: the same plan on another route, unless the plan only runs on its own route (then the first open plan). */
export function fallbackOption(primary: OptionForm, fallbackKey: string, c: Catalog): OptionForm | null {
  const dest = c.destinations.find(d => d.key === fallbackKey);
  if (!dest || fallbackKey === primary.destination_key) return null;
  const own = pkgData(c, primary.package_key);
  const locked = (k: string) => ((pkgData(c, k)?.destination_keys as string[] | undefined) ?? []);
  const fits = (k: string) => { const l = locked(k); return !l.length || l.includes(fallbackKey); };
  const pkgKey = own && fits(primary.package_key) ? primary.package_key : c.packages.find(p => fits(p.key) && !!p.live)?.key;
  if (!pkgKey) return null;
  const levels = packageLevels(pkgData(c, pkgKey) ?? {});
  const kitNames = new Set(kitsFor(c, pkgKey).map(k => k.name));
  const usual = entryData(dest).usual_nights;
  return {
    ...primary, package_key: pkgKey, destination_key: fallbackKey, sights: [], km_rate: null, vehicle_property_id: null,
    level: levels.length ? (primary.level && levels.includes(primary.level) ? primary.level : levels[0]) : null,
    kits: primary.kits.filter(k => kitNames.has(k)), extra_hours: 0,
    nights: typeof usual === "number" ? usual : primary.nights,
  };
}

export function tierFor(c: Catalog, packageKey: string): ResellerTier | null {
  const tiers = c.reseller_terms?.data.tiers ?? [];
  return tiers.find(t => !t.applies_to_package_keys?.length || t.applies_to_package_keys.includes(packageKey)) ?? null;
}

/** Commission choices within the tier's range, in 0.5 % steps, always including the default. */
export function commissionOptions(t: ResellerTier | null): string[] {
  if (!t) return [];
  const lo = t.min_commission_percent, hi = t.max_commission_percent;
  if (lo == null || hi == null) return [String(Number(t.commission_percent))];
  const out = new Set<string>();
  for (let v = Number(lo); v <= Number(hi) + 1e-9; v += 0.5) out.add(String(Math.round(v * 100) / 100));
  out.add(String(Number(t.commission_percent)));
  return Array.from(out).sort((a, b) => Number(a) - Number(b));
}

/** Extra-km rates the agent may apply: max down to min in steps of 10, plus the suggested rate. */
export function kmRateOptions(km: KmDetail | null): string[] {
  if (!km || km.rate_mode !== "range" || km.min_rate == null || km.max_rate == null) return [];
  const out = new Set<string>();
  for (let v = Number(km.max_rate); v >= Number(km.min_rate) - 1e-9; v -= 10) out.add(String(Math.round(v)));
  out.add(String(Number(km.min_rate)));
  if (km.suggested_rate) out.add(String(Number(km.suggested_rate)));
  return Array.from(out).sort((a, b) => Number(b) - Number(a));
}

/** A refusal's one-click fix as a button label and the change it makes. */
export function fixAction(fix: Json | null, c: Catalog | undefined): { label: string; patch: Partial<OptionForm> } | null {
  if (!fix) return null;
  if (typeof fix.nights === "number") {
    const n = fix.nights;
    return { label: n === 0 ? "Make it a day trip" : `Make it ${n} night${n === 1 ? "" : "s"}`, patch: { nights: n } };
  }
  if (fix.extra_hours === 0) return { label: "Return on time", patch: { extra_hours: 0 } };
  if (typeof fix.km_rate === "string") return { label: `Use ${money(fix.km_rate)} per km`, patch: { km_rate: fix.km_rate } };
  if (typeof fix.destination_key === "string") {
    const d = c?.destinations.find(x => x.key === fix.destination_key);
    return { label: `Switch to ${d ? entryName(d) : fix.destination_key}`, patch: { destination_key: fix.destination_key, sights: [] } };
  }
  if (typeof fix.level === "string") {
    const l = fix.level;
    return { label: /^\d+$/.test(l) ? `Use the ${money(l)} level` : `Use level ${l}`, patch: { level: l } };
  }
  if ("discount_percent" in fix && fix.discount_percent === null) return { label: "Remove the discount", patch: { discount_percent: null } };
  return null;
}

// ─── route editor ─────────────────────────────────────────────────────────────────────────────────────────

export const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 58);

export function emptyRoute(): RouteForm {
  return { key: null, name: "", description: "", usual_nights: "1", hours_from_base: "", km_from_base: "",
    places: [{ name: "", km: "", overnight: true }, { name: "Base", km: "", overnight: false }], sights: [] };
}

export function routeFromData(key: string, d: Json): RouteForm {
  return {
    key, name: String(d.name ?? ""), description: String(d.description ?? ""),
    usual_nights: d.usual_nights == null ? "" : String(d.usual_nights),
    hours_from_base: d.travel_hours_from_base == null ? "" : String(d.travel_hours_from_base),
    km_from_base: d.distance_km_from_base == null ? "" : String(d.distance_km_from_base),
    places: routeStops(d).map(s => ({ name: String(s.name ?? ""), km: s.distance_km_from_previous == null ? "" : String(s.distance_km_from_previous), overnight: !!s.overnight })),
    sights: routeSights(d).map(s => ({ name: s.name, km: String(s.km_round_trip) })),
  };
}

/** Kilometres from base to the first overnight stop (a sensible default for "distance from base"). */
export function kmToFirstNight(r: RouteForm): number {
  let sum = 0;
  for (const p of r.places) { sum += Number(p.km) || 0; if (p.overnight) return sum; }
  return sum;
}

export function validateRoute(r: RouteForm): string[] {
  const out: string[] = [];
  if (!r.name.trim()) out.push("Give the route a name.");
  if (r.places.length < 1) out.push("Add at least one place.");
  if (r.places.some(p => !p.name.trim())) out.push("Every place needs a name.");
  if (r.places.some(p => p.km === "" || Number(p.km) < 0 || !Number.isFinite(Number(p.km)))) out.push("Enter the km from the previous place for every place.");
  if (Number(r.usual_nights) > 0 && !r.places.some(p => p.overnight)) out.push("Mark where the caravan stays overnight.");
  const km = r.km_from_base === "" ? kmToFirstNight(r) : Number(r.km_from_base);
  if (km > 0 && !(Number(r.hours_from_base) > 0)) out.push("Enter the driving hours from base.");
  if (r.sights.some(s => !s.name.trim() || s.km === "")) out.push("Every sight needs a name and its km there and back.");
  const names = r.sights.map(s => s.name.trim().toLowerCase());
  if (new Set(names).size !== names.length) out.push("Two sights have the same name.");
  return out;
}

/** The destination record for a route form, keeping fields the editor does not show (best months, notes, stop hours). */
export function routeToData(r: RouteForm, original: Json = {}): Json {
  const oldStops = routeStops(original);
  const km = r.km_from_base === "" ? kmToFirstNight(r) : Number(r.km_from_base);
  const out: Json = {
    ...original,
    name: r.name.trim(), description: r.description.trim(),
    distance_km_from_base: String(km), travel_hours_from_base: String(Number(r.hours_from_base) || 0),
    stops: r.places.map((p, i) => {
      const keep = oldStops[i] && oldStops[i].name === p.name.trim() ? oldStops[i] : {};
      return { ...keep, name: p.name.trim(), order: i + 1, overnight: p.overnight, distance_km_from_previous: String(Number(p.km) || 0) };
    }),
    sights: r.sights.map(s => ({ name: s.name.trim(), km_round_trip: String(Number(s.km) || 0) })),
  };
  if (r.usual_nights === "") delete out.usual_nights;
  else out.usual_nights = Number(r.usual_nights);
  return out;
}
