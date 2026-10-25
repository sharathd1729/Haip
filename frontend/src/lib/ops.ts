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
  file_id: string | null; item_id: string | null; action: "open_file" | "resolve_item";
}
export interface OpsDayEntry {
  date: string; time: string | null; now: boolean; what: string; sub: string; file_id: string; tone: UnitTone;
}
export interface OpsToday {
  date: string; pack: string; unit_word: string; file_word: string;
  units: OpsUnit[]; needs: OpsNeed[]; day: OpsDayEntry[]; counts: { leaving: number; away: number; back: number };
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
  stay: {
    id: string; status: string; check_in: string; check_out: string; check_in_time: string | null; check_out_time: string | null;
    adults: number; children: number; guest_name: string; property_id: string; property_name: string | null; concierge_notes: string | null;
  };
  stage: { step: number; step_name: string; step_names: string[]; tasks: StageTask[]; next: string; next_key: string | null };
  details: {
    route: string | null; stops: string[]; allowance_km: string | null; extra_km_rate: string | null; rate_includes_gst: boolean;
    rate_source: string | null; driver_staff_id: string | null; helper_staff_id: string | null;
    start_odometer: number | null; end_odometer: number | null; start_odometer_photo_km: number | null;
  };
  crew: { driver: string | null; helper: string | null };
  gate: { blocking: string[]; red: string[]; green: number; total: number; ready: boolean };
  checklist: ChecklistItem[];
  account: OpsAccount;
  expenses: { id: string; category: string; amount: string; vendor: string | null; source: string; bill_date: string | null; has_photo: boolean }[];
  extras: { id: string; kind: string; label: string; amount: string; status: "proposed" | "approved" | "removed" }[];
  timeline: { at: string; text: string; auto: boolean }[];
  close_blockers: string[];
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
