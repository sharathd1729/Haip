// What each kind of business record is made of, mirroring backend/app/schemas/business_data.py. The server validates again and
// is the authority; these specs only decide which inputs to show and how to turn them into the JSON the server expects.

export type Option = { value: string; label: string };

export type Field =
  | { k: "text"; name: string; label: string; hint?: string; required?: boolean; multiline?: boolean; max?: number }
  | { k: "time"; name: string; label: string; hint?: string; required?: boolean }
  | { k: "int"; name: string; label: string; hint?: string; required?: boolean; min?: number; max?: number }
  | { k: "decimal"; name: string; label: string; hint?: string; required?: boolean; unit?: string }
  | { k: "bool"; name: string; label: string; hint?: string }
  | { k: "select"; name: string; label: string; options: Option[]; hint?: string; required?: boolean }
  | { k: "date"; name: string; label: string; hint?: string; required?: boolean }
  | { k: "tags"; name: string; label: string; hint?: string; placeholder?: string }
  | { k: "choices"; name: string; label: string; options: Option[]; hint?: string }
  | { k: "keys"; name: string; label: string; of: "destination" | "package"; hint?: string }
  | { k: "key"; name: string; label: string; of: "destination"; required?: boolean }
  | { k: "vehicles"; name: string; label: string; hint?: string }
  | { k: "object"; name: string; label: string; toggle: string; fields: Field[] }
  | { k: "list"; name: string; label: string; addLabel: string; itemLabel: string; fields: Field[]; min?: number };

export interface KindSpec {
  kind: string;
  label: string;
  plural: string;
  singleton: boolean;
  blurb: string;
  fields: Field[];
  /** One line shown in the list under the record name. */
  summary: (d: Record<string, unknown>) => string;
}

const WEEKDAYS: Option[] = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((l, i) => ({ value: String(i), label: l }));
const MONTHS: Option[] = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"].map((l, i) => ({ value: String(i + 1), label: l }));

const n = (v: unknown) => (Array.isArray(v) ? v.length : 0);
const s = (v: unknown) => (v == null ? "" : String(v));

export const KIND_SPECS: KindSpec[] = [
  {
    kind: "package", label: "Package", plural: "Packages", singleton: false,
    blurb: "What you sell: inclusions, limits and price by date. Prices here are the only ones the AI may quote.",
    summary: d => `${s(d.product).replace("_", " ")} · up to ${s(d.max_guests)} guests · ${n(d.rates)} rate${n(d.rates) === 1 ? "" : "s"}`,
    fields: [
      { k: "text", name: "name", label: "Package name", required: true, max: 120 },
      { k: "text", name: "summary", label: "Short description", multiline: true, max: 1000 },
      { k: "select", name: "product", label: "Type", required: true, options: [
        { value: "same_day", label: "Same day" }, { value: "overnight", label: "Overnight" },
        { value: "multiday", label: "Multi-day" }, { value: "route", label: "Fixed route" }] },
      { k: "int", name: "max_guests", label: "Most guests", required: true, min: 1, max: 50 },
      { k: "int", name: "min_nights", label: "Fewest nights", min: 0, max: 60, hint: "0 for a same-day package" },
      { k: "int", name: "max_nights", label: "Most nights", min: 0, max: 60 },
      { k: "decimal", name: "included_km", label: "Kilometres included (whole trip)", unit: "km", hint: "Or use the per-day allowance below, not both." },
      { k: "decimal", name: "included_km_per_day", label: "Kilometres included per day", unit: "km" },
      { k: "select", name: "day_count", label: "How days are counted", options: [
        { value: "calendar", label: "Calendar days (nights + 1)" }, { value: "noon_to_noon", label: "Noon to noon (24-hour days; a day trip is 1 day)" }] },
      { k: "int", name: "min_days", label: "Fewest days", min: 1, max: 60 },
      { k: "int", name: "duration_hours", label: "Package length (hours)", min: 1, max: 720, hint: "For a fixed-length package, e.g. 48. Shown on the quote." },
      { k: "vehicles", name: "vehicle_property_ids", label: "Vehicles", hint: "None selected = every vehicle." },
      { k: "tags", name: "inclusions", label: "Included", placeholder: "e.g. Driver and fuel" },
      { k: "tags", name: "exclusions", label: "Not included", placeholder: "e.g. Meals, tolls" },
      { k: "list", name: "rates", label: "Rates", addLabel: "Add a rate", itemLabel: "Rate", min: 1, fields: [
        { k: "text", name: "label", label: "Label", required: true, hint: "e.g. Peak season" },
        { k: "date", name: "valid_from", label: "From", required: true },
        { k: "date", name: "valid_to", label: "To", required: true },
        { k: "decimal", name: "amount", label: "Amount", required: true, unit: "₹" },
        { k: "select", name: "unit", label: "Charged", required: true, options: [
          { value: "night", label: "per night" }, { value: "package", label: "per package" }, { value: "day", label: "per day" }] },
        { k: "int", name: "min_nights", label: "Only for stays of at least (nights)", min: 0, max: 60 },
        { k: "choices", name: "days_of_week", label: "Only on these nights", options: WEEKDAYS, hint: "None selected = every day." },
        { k: "text", name: "level", label: "Level (optional)", max: 40, hint: "e.g. 40000. If one rate has a level, every rate needs one; the agent picks the level." },
        { k: "decimal", name: "floor_amount", label: "Lowest price (optional)", unit: "₹", hint: "The bottom of the price band. A discount can never go below it; above it, discounts still need approval." },
      ] },
      { k: "object", name: "extra_guest_charge", label: "Extra guests", toggle: "Charge for extra guests", fields: [
        { k: "int", name: "free_guests", label: "Guests included", min: 0, max: 50 },
        { k: "decimal", name: "per_guest", label: "Per extra guest", unit: "₹" },
        { k: "select", name: "unit", label: "Charged", options: [
          { value: "night", label: "per night" }, { value: "day", label: "per day" }, { value: "trip", label: "once for the trip" }] },
        { k: "decimal", name: "per_guest_per_night", label: "Per extra guest per night (older records)", unit: "₹", hint: "Fill this or the amount above, not both." },
      ] },
      { k: "object", name: "extra_km_charge", label: "Extra kilometres", toggle: "Charge for kilometres above the included amount", fields: [
        { k: "decimal", name: "per_km", label: "Fixed rate per extra km", unit: "₹", hint: "Or let the agent pick within a range below, not both." },
        { k: "decimal", name: "max_per_km", label: "Highest rate per km", unit: "₹" },
        { k: "decimal", name: "min_per_km", label: "Lowest rate per km", unit: "₹" },
        { k: "list", name: "ladder", label: "Suggested rate by extra distance", addLabel: "Add a step", itemLabel: "Step", fields: [
          { k: "decimal", name: "up_to_extra_km", label: "Up to (extra km)", unit: "km", hint: "Leave empty on the last step for any distance." },
          { k: "decimal", name: "per_km", label: "Suggested rate", required: true, unit: "₹" },
        ] },
      ] },
      { k: "object", name: "extra_hour_charge", label: "Extra hours", toggle: "Charge for a late return", fields: [
        { k: "decimal", name: "per_hour", label: "Per extra hour", required: true, unit: "₹" },
      ] },
      { k: "bool", name: "kits_included", label: "Experience kits are included in the price", hint: "Experience charges then show as included (₹0)." },
      { k: "tags", name: "at_actuals", label: "Billed at actuals (outside the total)", placeholder: "e.g. Tolls and parking" },
      { k: "list", name: "charges", label: "Optional charges and experiences", addLabel: "Add a charge", itemLabel: "Charge", fields: [
        { k: "text", name: "name", label: "Name", required: true },
        { k: "select", name: "kind", label: "Kind", options: [
          { value: "experience", label: "Experience" }, { value: "driver", label: "Driver" }, { value: "toll", label: "Toll" },
          { value: "night_halt", label: "Night halt" }, { value: "other", label: "Other" }] },
        { k: "decimal", name: "amount", label: "Amount", required: true, unit: "₹" },
        { k: "select", name: "unit", label: "Charged", options: [
          { value: "per_stay", label: "per stay" }, { value: "per_night", label: "per night" }, { value: "per_day", label: "per day" },
          { value: "per_person", label: "per person" }, { value: "per_unit", label: "per unit" }] },
      ] },
      { k: "keys", name: "destination_keys", label: "Destinations", of: "destination", hint: "Only published destinations can be linked." },
      { k: "decimal", name: "gst_percent", label: "GST", unit: "%" },
      { k: "int", name: "quote_valid_days", label: "A quote stays valid for (days)", min: 1, max: 60 },
      { k: "bool", name: "auto_bookable", label: "The AI may send this quote and payment link on its own",
        hint: "Only for the AI sales agent on autopilot: the overnight stay needs no check with the partner first. Leave off if unsure." },
      { k: "select", name: "audience", label: "Who it is for", options: [
        { value: "retail", label: "Guests (the AI may quote it)" }, { value: "b2b", label: "Partners only (never shown to guests)" }] },
    ],
  },
  {
    kind: "destination", label: "Destination", plural: "Destinations", singleton: false,
    blurb: "Where you go: distance, travel time, the stops on the way (with the return to base as the last stop) and optional sights.",
    summary: d => `${s(d.distance_km_from_base)} km · ${s(d.travel_hours_from_base)} h from base · ${n(d.stops)} stop${n(d.stops) === 1 ? "" : "s"}`,
    fields: [
      { k: "text", name: "name", label: "Name", required: true, max: 120 },
      { k: "text", name: "description", label: "Description", multiline: true, max: 2000 },
      { k: "decimal", name: "distance_km_from_base", label: "Distance from base", required: true, unit: "km" },
      { k: "decimal", name: "travel_hours_from_base", label: "Travel time from base", required: true, unit: "hours" },
      { k: "list", name: "stops", label: "Route stops", addLabel: "Add a stop", itemLabel: "Stop", fields: [
        { k: "text", name: "name", label: "Place", required: true },
        { k: "int", name: "order", label: "Order", required: true, min: 1, max: 50 },
        { k: "bool", name: "overnight", label: "Overnight stop" },
        { k: "decimal", name: "distance_km_from_previous", label: "Distance from previous", unit: "km" },
        { k: "decimal", name: "travel_hours_from_previous", label: "Time from previous", unit: "hours" },
      ] },
      { k: "list", name: "sights", label: "Optional sights guests can add", addLabel: "Add a sight", itemLabel: "Sight", fields: [
        { k: "text", name: "name", label: "Sight", required: true, max: 120 },
        { k: "decimal", name: "km_round_trip", label: "Km there and back", required: true, unit: "km" },
      ] },
      { k: "int", name: "usual_nights", label: "Usual nights", min: 0, max: 30 },
      { k: "choices", name: "best_months", label: "Best months", options: MONTHS },
      { k: "text", name: "notes", label: "Notes", multiline: true, max: 1000 },
      { k: "bool", name: "auto_bookable", label: "Overnight stays on this route need no partner check",
        hint: "Lets the AI sales agent on autopilot send the quote and payment link for this route on its own. Leave off if unsure." },
    ],
  },
  {
    kind: "itinerary", label: "Itinerary", plural: "Itineraries", singleton: false,
    blurb: "A day-by-day plan with overnight locations, tied to a destination and its packages.",
    summary: d => `${s(d.nights)} night${d.nights === 1 ? "" : "s"} · ${n(d.days)} day${n(d.days) === 1 ? "" : "s"} · ${s(d.destination_key)}`,
    fields: [
      { k: "text", name: "name", label: "Name", required: true, max: 120 },
      { k: "key", name: "destination_key", label: "Destination", of: "destination", required: true },
      { k: "int", name: "nights", label: "Nights", required: true, min: 0, max: 60 },
      { k: "list", name: "days", label: "Days", addLabel: "Add a day", itemLabel: "Day", min: 1, fields: [
        { k: "int", name: "day", label: "Day number", required: true, min: 1, max: 60 },
        { k: "text", name: "title", label: "Title", required: true },
        { k: "tags", name: "stops", label: "Stops", placeholder: "e.g. Madikeri Fort" },
        { k: "text", name: "overnight_location", label: "Night is spent at" },
        { k: "text", name: "notes", label: "Notes", multiline: true },
      ] },
      { k: "keys", name: "package_keys", label: "Packages this applies to", of: "package" },
    ],
  },
  {
    kind: "stay_rules", label: "Check-in and house rules", plural: "Check-in and house rules", singleton: true,
    blurb: "Times and rules guests are told about.",
    summary: d => `check-in ${s(d.check_in_time)} · check-out ${s(d.check_out_time)}`,
    fields: [
      { k: "time", name: "check_in_time", label: "Check-in time", required: true },
      { k: "time", name: "check_out_time", label: "Check-out time", required: true },
      { k: "bool", name: "early_check_in_allowed", label: "Early check-in allowed" },
      { k: "int", name: "min_age", label: "Minimum age", min: 0, max: 99 },
      { k: "bool", name: "id_required", label: "Photo ID required" },
      { k: "tags", name: "house_rules", label: "House rules", placeholder: "e.g. No smoking inside" },
    ],
  },
  {
    kind: "payment_policy", label: "Payment terms", plural: "Payment terms", singleton: true,
    blurb: "Advance and balance. Cannot be published until Ratha confirms the terms.",
    summary: d => `${s(d.advance_percent)}% advance · balance ${s(d.balance_due_days_before_checkin)} days before`,
    fields: [
      { k: "decimal", name: "advance_percent", label: "Advance", required: true, unit: "%" },
      { k: "int", name: "balance_due_days_before_checkin", label: "Balance due (days before check-in)", required: true, min: 0, max: 365 },
      { k: "list", name: "instalments", label: "Instalments (optional)", addLabel: "Add an instalment", itemLabel: "Instalment", fields: [
        { k: "text", name: "label", label: "Label", required: true },
        { k: "decimal", name: "percent", label: "Share", required: true, unit: "%" },
        { k: "int", name: "due_days_before_checkin", label: "Due (days before check-in)", required: true, min: 0, max: 365 },
      ] },
      { k: "choices", name: "accepted_methods", label: "Accepted methods", options: [
        { value: "payment_link", label: "Payment link" }, { value: "upi", label: "UPI" }, { value: "card", label: "Card" },
        { value: "bank_transfer", label: "Bank transfer" }, { value: "cash", label: "Cash" }] },
      { k: "int", name: "payment_link_expiry_hours", label: "Payment link valid for (hours)", min: 1, max: 720 },
      { k: "bool", name: "confirmed_by_ratha", label: "Ratha has confirmed these terms", hint: "Tick only when Ratha has confirmed them. The AI never states unconfirmed terms." },
    ],
  },
  {
    kind: "cancellation_policy", label: "Cancellation terms", plural: "Cancellation terms", singleton: true,
    blurb: "Refund by how early a guest cancels. Refunds themselves stay a human decision.",
    summary: d => `${n(d.tiers)} refund tier${n(d.tiers) === 1 ? "" : "s"}`,
    fields: [
      { k: "list", name: "tiers", label: "Refund tiers", addLabel: "Add a tier", itemLabel: "Tier", min: 1, fields: [
        { k: "int", name: "days_before", label: "Cancelled at least this many days before check-in", required: true, min: 0, max: 365 },
        { k: "decimal", name: "refund_percent", label: "Refund", required: true, unit: "%" },
      ] },
      { k: "tags", name: "non_refundable_items", label: "Never refunded", placeholder: "e.g. Booking fee" },
      { k: "bool", name: "confirmed_by_ratha", label: "Ratha has confirmed these terms", hint: "Tick only when Ratha has confirmed them." },
    ],
  },
  {
    kind: "discount_policy", label: "Discount limits", plural: "Discount limits", singleton: true,
    blurb: "How much the AI and the team may discount, and who approves above that.",
    summary: d => `up to ${s(d.max_discount_percent)}% · approval above ${s(d.requires_approval_above_percent ?? 0)}%`,
    fields: [
      { k: "decimal", name: "max_discount_percent", label: "Largest discount allowed", required: true, unit: "%" },
      { k: "decimal", name: "max_discount_amount", label: "Largest discount in rupees", unit: "₹" },
      { k: "decimal", name: "min_booking_amount", label: "No discount below this booking value", unit: "₹", hint: "Package price before tax. Smaller bookings are never discounted." },
      { k: "decimal", name: "requires_approval_above_percent", label: "Needs approval above", unit: "%" },
      { k: "choices", name: "approver_roles", label: "Who can approve", options: [
        { value: "owner", label: "Owner" }, { value: "manager", label: "Manager" }, { value: "reservations", label: "Reservations" }] },
      { k: "select", name: "floor_rule", label: "Floor", options: [
        { value: "never_below_base", label: "Never below the base price" }, { value: "none", label: "No floor" }] },
      { k: "bool", name: "stackable", label: "Can combine with other offers" },
      { k: "tags", name: "valid_conditions", label: "Conditions", placeholder: "e.g. Stays of 3+ nights" },
    ],
  },
  {
    kind: "reseller_terms", label: "Reseller terms", plural: "Reseller terms", singleton: true,
    blurb: "Commission and discount limits for travel agents and other resellers.",
    summary: d => `${n(d.tiers)} tier${n(d.tiers) === 1 ? "" : "s"}`,
    fields: [
      { k: "list", name: "tiers", label: "Tiers", addLabel: "Add a tier", itemLabel: "Tier", min: 1, fields: [
        { k: "text", name: "name", label: "Tier name", required: true },
        { k: "decimal", name: "commission_percent", label: "Commission", required: true, unit: "%" },
        { k: "decimal", name: "max_discount_percent", label: "Largest discount they may offer", unit: "%" },
        { k: "decimal", name: "min_commission_percent", label: "Lowest commission the agent may pick", unit: "%" },
        { k: "decimal", name: "max_commission_percent", label: "Highest commission the agent may pick", unit: "%" },
        { k: "int", name: "min_days", label: "Fewest days", min: 1, max: 60 },
        { k: "decimal", name: "min_billing", label: "Lowest billing before tax", unit: "₹" },
        { k: "keys", name: "applies_to_package_keys", label: "Packages", of: "package", hint: "None selected = every package." },
      ] },
      { k: "text", name: "settlement_notes", label: "How commission is settled", multiline: true, max: 1000 },
    ],
  },
];

export const SPEC_BY_KIND: Record<string, KindSpec> = Object.fromEntries(KIND_SPECS.map(k => [k.kind, k]));

export type Json = Record<string, unknown>;

/** A blank value for a field. Required lists start with one row; optional things start empty. */
export function blankFor(fields: Field[]): Json {
  const out: Json = {};
  for (const f of fields) {
    if (f.k === "list") out[f.name] = f.min ? [blankFor(f.fields)] : [];
    else if (f.k === "tags" || f.k === "choices" || f.k === "keys" || f.k === "vehicles") out[f.name] = [];
    else if (f.k === "bool") out[f.name] = f.name === "id_required";
    else if (f.k === "select") out[f.name] = f.required ? f.options[0].value : "";
    else if (f.k !== "object") out[f.name] = "";
  }
  return out;
}

const isEmpty = (v: unknown) => v === "" || v == null || (Array.isArray(v) && v.length === 0);

/** The JSON the server expects: numbers as numbers, money kept as text, empty optional fields left out. */
export function toPayload(fields: Field[], value: Json): Json {
  const out: Json = {};
  for (const f of fields) {
    const v = value[f.name];
    if (f.k === "object") {
      if (v && typeof v === "object") out[f.name] = toPayload(f.fields, v as Json);
    } else if (f.k === "list") {
      const rows = (Array.isArray(v) ? v : []).map(r => toPayload(f.fields, r as Json));
      if (rows.length || f.min) out[f.name] = rows;
    } else if (f.k === "int") {
      if (!isEmpty(v)) out[f.name] = Number(v);
    } else if (f.k === "choices" && f.options.every(o => /^\d+$/.test(o.value))) {
      if (!isEmpty(v)) out[f.name] = (v as string[]).map(Number);
    } else if (f.k === "bool") {
      out[f.name] = !!v;
    } else if (f.k === "tags" || f.k === "choices" || f.k === "keys" || f.k === "vehicles") {
      out[f.name] = Array.isArray(v) ? v : [];
    } else if (!isEmpty(v)) {
      out[f.name] = typeof v === "string" ? v.trim() : v;
    }
  }
  return out;
}

/** Server JSON back into form values (numbers become text so inputs stay controlled). */
export function fromPayload(fields: Field[], data: Json): Json {
  const out: Json = {};
  for (const f of fields) {
    const v = data?.[f.name];
    if (f.k === "object") {
      if (v && typeof v === "object") out[f.name] = fromPayload(f.fields, v as Json);
    } else if (f.k === "list") {
      out[f.name] = (Array.isArray(v) ? v : []).map(r => fromPayload(f.fields, r as Json));
    } else if (f.k === "choices" || f.k === "tags" || f.k === "keys" || f.k === "vehicles") {
      out[f.name] = (Array.isArray(v) ? v : []).map(String);
    } else if (f.k === "bool") {
      out[f.name] = !!v;
    } else {
      out[f.name] = v == null ? "" : String(v);
    }
  }
  return out;
}
