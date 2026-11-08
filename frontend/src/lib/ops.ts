// Ops module (caravan pack first): the shapes GET /ops/files/today and GET /ops/files/{id} return, and the small pure rules the
// two screens share. Every business rule (what needs a person, what is ready, money) is decided by the server
// (ops_today_service, ops_trip_service, ops_money); this file only turns its answers into words and buttons.
import { formatINR } from "@/lib/utils";

export type Level = "red" | "amber";
export type UnitTone = "red" | "amber" | "ok" | "idle";

export interface OpsUnit {
  property_id: string; name: string; tone: UnitTone; status: string; line: string;
  problem: string | null; file_id: string | null; ready_pct: number | null;
}
export interface OpsNeed {
  key: string; level: Level; unit: string; title: string; detail: string;
  file_id: string | null; item_id: string | null; action: "open_file" | "resolve_item" | "open_fleet" | "open_staff";
  item_kind?: string; // gps_off_route: the card offers "Approved detour" (backend gps_alerts.approve_detour)
}
export interface OpsDayEntry {
  date: string; time: string | null; now: boolean; what: string; sub: string; file_id: string; tone: UnitTone;
}
export interface OpsToday {
  date: string; pack: string; unit_word: string; file_word: string;
  units: OpsUnit[]; needs: OpsNeed[]; day: OpsDayEntry[]; counts: Record<string, number>;  // caravan leaving/away/back, villa arriving/staying/leaving
}

export interface StageTask { key: string; label: string; done: boolean; hint: string | null }
export interface ChecklistItem {
  key: string; label: string; critical: boolean; source: "staff" | "system" | "manager"; photo_required: boolean;
  status: "pending" | "green" | "red"; note: string | null; has_photo: boolean;
  ai_verdict: { ok: boolean; problems: string[] } | null; set_at: string | null;
}
export interface OpsAccount {
  package_total: string; addons_total: string; distance_km: number | null; allowance_km: string | null; extra_km: number;
  extra_km_rate: string | null; rate_includes_gst: boolean; extra_km_charge: string; total_revenue: string; gst_percent: string;
  paid: string; outstanding: string; expenses_by_category: Record<string, string>; total_expenses: string; net_cash: string;
  deposit: { amount: string; status: string; deducted: string } | null; extras_waiting: number;
}
export interface OpsFileFull {
  id: string; pack: string; state: string; step: number; step_name: string; next: string;
  /** Ops 2: which flow and state machine run this file (stay = villa, rental, homestay and room packs). */
  flow: "trip" | "whole_unit" | "room"; machine: "trip" | "stay"; unit_word: string;
  stay: {
    id: string; status: string; check_in: string; check_out: string; check_in_time: string | null; check_out_time: string | null;
    adults: number; children: number; guest_name: string; property_id: string; property_name: string | null; concierge_notes: string | null;
  };
  stage: { step: number; step_name: string; step_names: string[]; tasks: StageTask[]; next: string; next_key: string | null };
  details: {
    route: string | null; stops: string[]; allowance_km: string | null; extra_km_rate: string | null; rate_includes_gst: boolean;
    rate_source: string | null; driver_staff_id: string | null; helper_staff_id: string | null;
    start_odometer: number | null; end_odometer: number | null; start_odometer_photo_km: number | null;
  } & Partial<VillaDetails>;
  crew: { driver: string | null; helper: string | null };
  gate: { blocking: string[]; red: string[]; green: number; total: number; ready: boolean };
  checklist: ChecklistItem[];
  account: OpsAccount;
  expenses: { id: string; category: string; amount: string; vendor: string | null; source: string; bill_date: string | null; has_photo: boolean }[];
  extras: { id: string; kind: string; label: string; amount: string; status: "proposed" | "approved" | "removed" }[];
  timeline: { at: string; text: string; auto: boolean }[];
  close_blockers: string[];
  fleet_problems: string[];
  guest_form: {
    submitted_at: string | null; link: string | null; guests: { name: string; age: number | null; id: string }[];
    emergency_name?: string; emergency_phone?: string; food?: string; requests?: string; signed_name?: string;
  };
  return_check: { words: string; damage: string[]; items: { key: string; label: string; status: "pending" | "green" | "red"; note: string | null; has_photo: boolean }[] };
  messages: { kind: string; recipient: string; status: "sent" | "failed"; via: string | null; reason: string | null; sent_at: string | null }[];
  // Villa pack only (ops_files._villa_extra): the stay's people, check-out inspection, mid-stay cleans, the booking's requests.
  people?: { caretaker: string | null; cook: string | null; cleaner: string | null };
  inspection?: ChecklistItem[];
  cleaning?: { id: string; due_at: string | null; status: "open" | "done" | "cancelled" }[];
  service_requests?: { id: string; title: string; status: "open" | "done"; due_date: string | null }[];
}

// ── Villa pack (ops_stay_service): the stay file's own details ──────────────────────────────────────────────────────
export interface Meal {
  id: string; date: string; meal: "breakfast" | "lunch" | "dinner"; guests: number; food: "veg" | "non_veg" | "mixed";
  notes: string | null; sent_at: string | null; confirmed_at: string | null; confirmed_by: string | null;
}
export interface VillaDetails {
  caretaker_staff_id: string | null; cook_staff_id: string | null; cleaner_staff_id: string | null; keys_handed: boolean;
  deposit_collected: boolean | null; check_in_note: string | null; meals: Meal[]; deposit_decision: "refund" | "deduct" | null;
  deposit_reason: string | null; deposit_evidence: string[];
}
export const FOOD_LABELS: Record<Meal["food"], string> = { veg: "Veg", non_veg: "Non-veg", mixed: "Veg + non-veg" };

export type StayAction =
  | { kind: "people" | "checkin" | "checkout" | "deposit" | "checklist" | "inspection" | "extras" | "meals" | "cleaning" | "close" | "booking"; label: string }
  | { kind: "settle"; step: "return_checked" | "report_approved"; label: string };

/** The villa file's "Next step" button for the stage's next_key (ops_stay_service.stage). Welcoming the guest, the deposit,
 *  settling and closing are the manager's taps (ops.manage); null = nothing for this person to tap. */
export function stayNextAction(key: string | null | undefined, canManage: boolean): StayAction | null {
  switch (key) {
    case "people": return { kind: "people", label: "Pick the people" };
    case "gate": return { kind: "checklist", label: "See the checklist" };
    case "checkin": return canManage ? { kind: "checkin", label: "Check in the guest" } : null;
    case "extras": return { kind: "extras", label: "See the extras" };
    case "clean": return { kind: "cleaning", label: "See the cleaning" };
    case "meals": return { kind: "meals", label: "See the meal plan" };
    case "checkout": return { kind: "checkout", label: "Guest has left: check out" };
    case "inspect": return { kind: "inspection", label: "See the inspection" };
    case "ret": return canManage ? { kind: "settle", step: "return_checked", label: "Inspection is done" } : null;
    case "bal": return { kind: "booking", label: "Open the booking" };
    case "deposit": return canManage ? { kind: "deposit", label: "Decide the deposit" } : null;
    case "rep": return canManage ? { kind: "settle", step: "report_approved", label: "Approve the report" } : null;
    case "close": return canManage ? { kind: "close", label: "Close the stay" } : null;
    default: return null;
  }
}

// ── Fleet (GET /ops/fleet, ops_fleet_view) and staff (GET /ops/staff) ──────────────────────────────────────────────────
export type FleetLevel = Level | null;
export interface FleetPaper { id: string; kind: string; name: string; number: string | null; expires_on: string | null; level: FleetLevel; words: string; has_file: boolean }
export interface FleetCardData {
  property_id: string; name: string; km: number | null; tone: "red" | "amber" | "ok"; problems: string[];
  papers: FleetPaper[]; missing_papers: string[];
  defects: { id: string; title: string; detail: string | null; severity: "critical" | "normal"; source: "person" | "photo"; file_id: string | null; reported_at: string | null }[];
  services: { id: string; name: string; due_on: string | null; due_km: number | null; status: "open" | "done"; level: FleetLevel; words: string }[];
  inventory: { id: string; name: string; par: number; count: number | null; low: boolean; counted_at: string | null }[];
}
export interface OpsStaff {
  id: string; name: string; phone_e164: string; active: boolean; whatsapp_opt_in_at: string | null; notes: string | null;
  duties: { duty: string; property_id: string | null }[]; licence_number: string | null; licence_expires_on: string | null;
}
/** Paper kinds (backend schemas/ops_fleet.py PAPER_KINDS): vehicle papers first. */
export const VEHICLE_PAPERS: Record<string, string> = {
  insurance: "Insurance", permit: "Permit", fc: "Fitness certificate (FC)", puc: "Pollution certificate (PUC)",
  ais140: "AIS-140 tracker certificate", other: "Other paper",
};
/** Duties (backend schemas/ops.py DUTIES), in the words the owner uses. */
export const DUTY_LABELS: Record<string, string> = {
  driver: "Driver", caretaker: "Helper / caretaker", housekeeping: "Housekeeping", maintenance: "Maintenance",
  front_desk: "Front desk", fnb: "Food", ops_manager: "Ops manager",
};
/** A licence that ends within 30 days is amber, within 7 days (or gone) red: the same rule as the server's papers. */
export function expiryLevel(iso: string | null, todayIso: string): FleetLevel {
  if (!iso) return null;
  const days = Math.round((new Date(`${iso}T00:00:00Z`).getTime() - new Date(`${todayIso}T00:00:00Z`).getTime()) / 86_400_000);
  return days <= 7 ? "red" : days <= 30 ? "amber" : null;
}

/** Roles behind the ops capabilities (backend migration 178): ops.read, ops.write, ops.manage. */
export const OPS_READ_ROLES = ["owner", "manager", "reservations", "concierge", "foh"];
export const canWriteOps = (role?: string | null) => ["owner", "manager", "concierge", "foh"].includes(role ?? "");
export const canManageOps = (role?: string | null) => role === "owner" || role === "manager";

/** Unit cards sit on top of the list only for small businesses (owner pick: six units or fewer). */
export const showUnitCards = (units: OpsUnit[]) => units.length > 0 && units.length <= 6;

export const rupees = (v: string | number | null | undefined) => formatINR(Number(v ?? 0));

function clock(hhmm: string): string {
  const [h, m] = hhmm.split(":").map(Number);
  if (!Number.isFinite(h) || !Number.isFinite(m)) return hhmm;
  const ap = h >= 12 ? "pm" : "am";
  const h12 = h % 12 || 12;
  return m ? `${h12}:${String(m).padStart(2, "0")} ${ap}` : `${h12} ${ap}`;
}

/** "Now" | "Today 7 am" | "Tomorrow 6:30 pm" | "Tue 28 Oct", from the server's date + "HH:MM" (workspace time). */
export function whenLabel(e: Pick<OpsDayEntry, "date" | "time" | "now">, todayIso: string): string {
  if (e.now) return "Now";
  const t = e.time ? ` ${clock(e.time)}` : "";
  const day = new Date(`${e.date}T00:00:00Z`).getTime(), today = new Date(`${todayIso}T00:00:00Z`).getTime();
  const diff = Math.round((day - today) / 86_400_000);
  if (diff === 0) return `Today${t}`;
  if (diff === 1) return `Tomorrow${t}`;
  return new Date(`${e.date}T00:00:00Z`).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" }) + t;
}

export type NextAction =
  | { kind: "accept" | "crew" | "dispatch" | "return" | "close" | "checklist" | "extras" | "booking"; label: string }
  | { kind: "settle"; step: "return_checked" | "report_approved"; label: string };

/** What the big "Next step" button does for the stage's next_key. null = nothing for this person to tap (waiting, or the
 *  step needs ops.manage). Dispatch, settling and closing stay the manager's taps. */
export function nextAction(key: string | null | undefined, canManage: boolean): NextAction | null {
  switch (key) {
    case "route": return { kind: "accept", label: "Set route and km" };
    case "crew": return { kind: "crew", label: "Pick driver and helper" };
    case "pay": case "bal": case "dep": return { kind: "booking", label: "Open the booking" };
    case "extras": return { kind: "extras", label: "See the extras" };
    case "gate": return { kind: "checklist", label: "See the checklist" };
    case "end": return { kind: "return", label: "Enter end odometer" };
    case "start": return canManage ? { kind: "dispatch", label: "Dispatch" } : null;
    case "ret": return canManage ? { kind: "settle", step: "return_checked", label: "Vehicle is checked" } : null;
    case "rep": return canManage ? { kind: "settle", step: "report_approved", label: "Approve the report" } : null;
    case "close": return canManage ? { kind: "close", label: "Close the trip" } : null;
    default: return null;
  }
}

export const EXPENSE_LABELS: Record<string, string> = {
  fuel: "Fuel", toll: "Toll", parking: "Parking", driver: "Driver", helper: "Helper", repair: "Repair",
  consumables: "Consumables", groceries: "Groceries", other: "Other",
};
