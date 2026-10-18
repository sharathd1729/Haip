import { describe, expect, it } from "vitest";
import {
  canApprove, commissionOptions, emptyRoute, fallbackOption, fixAction, kmRateOptions, money, packageLevels, packageTag, routeFromData,
  routeKm, routeToData, toOptionPayload, validateRoute,
} from "./quoteHelpers";
import type { Catalog, CatalogEntry, KmDetail, OptionForm } from "./types";

const rec = (data: Record<string, unknown>, created_by = "u1") => ({
  record_id: "r", version: 1, status: "published", data, change_note: null, effective_from: null, created_by, created_by_name: null,
  created_at: null, published_at: null,
});
const entry = (key: string, data: Record<string, unknown>): CatalogEntry => ({ key, live: rec(data), draft: null });

const catalog: Catalog = {
  today: "2026-10-18",
  packages: [
    entry("coorg-48", { name: "Coorg 48-hour Retreat", destination_keys: ["coorg"], rates: [{ amount: "70000.00", unit: "package" }] }),
    entry("day-rate", { name: "Day rate", destination_keys: [], rates: [{ amount: "25000.00", unit: "day" }] }),
    entry("all-inc", { name: "All-inclusive", rates: [{ amount: "45000", unit: "day", level: "45000" }, { amount: "35000", unit: "day", level: "35000" }] }),
  ],
  destinations: [entry("coorg", { name: "Coorg", usual_nights: 2 }), entry("krs", { name: "KRS Backwaters", usual_nights: 1 })],
  kits: [{ name: "Culinary", amount: "5000.00", unit: "per_stay", package_keys: ["coorg-48", "day-rate"] },
         { name: "Wellness", amount: "5000.00", unit: "per_stay", package_keys: ["coorg-48"] }],
  reseller_terms: null, advance_percent: "50.00", vehicles: [],
  permissions: { user_id: "u1", is_owner: false, can_quote: true, can_draft: true, can_publish: true },
};

const primary: OptionForm = {
  package_key: "coorg-48", start_date: "2026-10-30", nights: 2, adults: 5, children: 1, level: null, destination_key: "coorg",
  sights: ["Raja's Seat"], km_rate: null, extra_hours: 0, kits: ["Culinary", "Wellness"], discount_percent: null,
  vehicle_property_id: "v1", channel: "direct", reseller_tier: null, commission_percent: "10",
};

describe("formatting", () => {
  it("shows money in lakh grouping and a dash for nothing", () => {
    expect(money("8988000.00")).toBe("₹89,88,000");
    expect(money("89880.00")).toBe("₹89,880");
    expect(money(null)).toBe("—");
  });

  it("describes a plan's price the way the rate card does", () => {
    expect(packageTag(entry("x", { rates: [{ amount: "70000.00", unit: "package" }] }).live!.data)).toBe("₹70,000 + tax");
    expect(packageTag({ rates: [{ amount: "25000", unit: "day" }] })).toBe("₹25,000 a day + tax");
    expect(packageTag({ rates: [{ amount: "45000", unit: "day" }, { amount: "35000", unit: "day" }] })).toBe("₹35,000-₹45,000 a day + tax");
    expect(packageLevels(catalog.packages[2].live!.data)).toEqual(["35000", "45000"]);
  });
});

describe("request payloads", () => {
  it("leaves out empty choices and reseller fields when selling direct", () => {
    const out = toOptionPayload({ ...primary, km_rate: "", discount_percent: "0" });
    expect(out).toEqual({ package_key: "coorg-48", start_date: "2026-10-30", nights: 2, adults: 5, children: 1, sights: ["Raja's Seat"],
      kits: ["Culinary", "Wellness"], extra_hours: 0, channel: "direct", destination_key: "coorg", vehicle_property_id: "v1" });
    expect(toOptionPayload({ ...primary, channel: "reseller" }).commission_percent).toBe("10");
  });

  it("builds the fallback on another route, switching away from a plan locked to the first route", () => {
    const fb = fallbackOption(primary, "krs", catalog)!;
    expect(fb.package_key).toBe("day-rate");
    expect(fb.destination_key).toBe("krs");
    expect(fb.nights).toBe(1);
    expect(fb.sights).toEqual([]);
    expect(fb.vehicle_property_id).toBeNull();
    expect(fb.kits).toEqual(["Culinary"]);                       // Wellness is not offered with the day rate
    expect(fallbackOption(primary, "coorg", catalog)).toBeNull();
    expect(fallbackOption(primary, "nowhere", catalog)).toBeNull();
  });
});

describe("agent choices", () => {
  it("offers commission in half-percent steps within the tier", () => {
    expect(commissionOptions({ name: "T", commission_percent: "10.00", min_commission_percent: "7.50", max_commission_percent: "11.50" }))
      .toEqual(["7.5", "8", "8.5", "9", "9.5", "10", "10.5", "11", "11.5"]);
    expect(commissionOptions({ name: "T", commission_percent: "8" })).toEqual(["8"]);
  });

  it("offers km rates from the top of the range down and includes the suggestion", () => {
    const km = { rate_mode: "range", min_rate: "60.00", max_rate: "100.00", suggested_rate: "90.00" } as KmDetail;
    expect(kmRateOptions(km)).toEqual(["100", "90", "80", "70", "60"]);
    expect(kmRateOptions({ ...km, rate_mode: "fixed" })).toEqual([]);
  });

  it("turns a refusal's fix into a button", () => {
    expect(fixAction({ nights: 3 }, catalog)).toEqual({ label: "Make it 3 nights", patch: { nights: 3 } });
    expect(fixAction({ destination_key: "coorg" }, catalog)?.label).toBe("Switch to Coorg");
    expect(fixAction({ km_rate: "90.00" }, catalog)).toEqual({ label: "Use ₹90 per km", patch: { km_rate: "90.00" } });
    expect(fixAction({ extra_hours: 0 }, catalog)?.patch).toEqual({ extra_hours: 0 });
    expect(fixAction(null, catalog)).toBeNull();
  });

  it("lets a publisher approve only someone else's draft unless they are the owner", () => {
    expect(canApprove(rec({}, "u2"), catalog.permissions)).toBe(true);
    expect(canApprove(rec({}, "u1"), catalog.permissions)).toBe(false);
    expect(canApprove(rec({}, "u1"), { ...catalog.permissions, is_owner: true })).toBe(true);
    expect(canApprove(rec({}, "u2"), { ...catalog.permissions, can_publish: false })).toBe(false);
  });
});

describe("route editor", () => {
  it("checks the route before saving", () => {
    expect(validateRoute(emptyRoute())).toContain("Give the route a name.");
    const ok = { ...emptyRoute(), name: "Chikmagalur", hours_from_base: "5", places: [{ name: "Estate", km: "250", overnight: true }, { name: "Base", km: "250", overnight: false }] };
    expect(validateRoute(ok)).toEqual([]);
    expect(validateRoute({ ...ok, hours_from_base: "" })).toContain("Enter the driving hours from base.");
  });

  it("round-trips a destination and keeps fields it does not edit", () => {
    const data = { name: "KRS", description: "River", distance_km_from_base: "160", travel_hours_from_base: "4", best_months: [11],
      usual_nights: 1, stops: [{ name: "KRS site", order: 1, distance_km_from_previous: "160", overnight: true, travel_hours_from_previous: "4" },
        { name: "Base", order: 2, distance_km_from_previous: "160", overnight: false }], sights: [{ name: "Brindavan", km_round_trip: "6" }] };
    const form = routeFromData("krs", data);
    expect(form.places.map(p => p.km)).toEqual(["160", "160"]);
    const back = routeToData(form, data);
    expect(back.best_months).toEqual([11]);
    expect(routeKm(back)).toBe(320);
    expect((back.stops as { travel_hours_from_previous?: string }[])[0].travel_hours_from_previous).toBe("4");
    expect(back.sights).toEqual([{ name: "Brindavan", km_round_trip: "6" }]);
    expect(back.usual_nights).toBe(1);
  });
});
