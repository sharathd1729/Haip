// Ops roster screens (Ops › Staff › Who is on duty / If nobody answers). Pure helpers, tested in opsRoster.test.ts.
// The server decides who an alert reaches (roster_service); these only lay out what /ops/shifts, /ops/shift-overrides and
// /ops/on-duty return. Shift times are the workspace's local minutes; an end at or before the start crosses midnight.
import { DUTY_LABELS, type OpsStaff } from "@/lib/ops";

export interface ShiftPattern { id: string; staff_id: string; duty: string; property_id: string | null; weekday: number; start_minute: number; end_minute: number; active: boolean }
export interface ShiftOverride { id: string; staff_id: string; kind: "leave" | "extra" | "swap"; starts_at: string; ends_at: string; duty: string | null; replacement_staff_id: string | null }
export interface ChainSpec { type: "on_shift" | "duty" | "role" | "staff"; duty?: string; role?: string; staff_id?: string }
export interface OnDutyStep { step: number; spec: ChainSpec; recipients: string[] }
export interface OnDuty { on_shift: { id: string; name: string }[]; steps: OnDutyStep[] }
export interface OpsSettings { sla: Record<Severity, [number, number]>; quiet_hours: { start: string; end: string } }

/** Backend schemas/ops.py DUTIES, in screen order. */
export const DUTY_ORDER = ["caretaker", "fnb", "driver", "housekeeping", "maintenance", "front_desk", "ops_manager"];
export const SEVERITIES = ["critical", "high", "normal", "low"] as const;
export type Severity = (typeof SEVERITIES)[number];
export const SEVERITY_LABELS: Record<Severity, string> = { critical: "Critical", high: "High", normal: "Normal", low: "Low" };
/** Backend DEFAULT_SLA_MINUTES ack column, shown until settings load. */
export const DEFAULT_ACK: Record<Severity, number> = { critical: 5, high: 15, normal: 60, low: 240 };
export const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
// shortcut: the web app has no workspace-timezone hook yet (other screens hard-code IST too); read tenants.timezone when one exists.
export const WORKSPACE_TZ = "Asia/Kolkata";

export const hhmm = (min: number) => `${String(Math.floor(min / 60)).padStart(2, "0")}:${String(min % 60).padStart(2, "0")}`;
export const isNight = (p: Pick<ShiftPattern, "start_minute" | "end_minute">) => p.end_minute <= p.start_minute;
export const minutesLabel = (m: number) => (m < 60 ? `${m} min` : m % 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : m === 60 ? "1 hour" : `${m / 60} hours`);

const addDays = (iso: string, n: number) => { const d = new Date(`${iso}T00:00:00Z`); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
/** Monday (YYYY-MM-DD) of the week holding `iso`. */
export function mondayOf(iso: string): string {
  const wd = (new Date(`${iso}T00:00:00Z`).getUTCDay() + 6) % 7;
  return addDays(iso, -wd);
}
/** One whole local day as the [starts_at, ends_at) a leave override needs (IST: see WORKSPACE_TZ). */
export const dayRange = (iso: string): [string, string] => [`${iso}T00:00:00+05:30`, `${addDays(iso, 1)}T00:00:00+05:30`];
export const weekDates = (monday: string) => WEEKDAYS.map((_, i) => addDays(monday, i));
export const shiftWeek = (monday: string, weeks: number) => addDays(monday, weeks * 7);
const localDate = (ts: string, tz: string) => new Date(ts).toLocaleDateString("en-CA", { timeZone: tz });
const localMinute = (ts: string, tz: string) => {
  const [h, m] = new Date(ts).toLocaleTimeString("en-GB", { timeZone: tz, hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).split(":").map(Number);
  return h * 60 + m;
};
/** True when the override touches that local date (ends_at is exclusive). */
function covers(o: ShiftOverride, iso: string, tz: string): boolean {
  return localDate(o.starts_at, tz) <= iso && localDate(new Date(new Date(o.ends_at).getTime() - 1).toISOString(), tz) >= iso;
}

export type CellItem =
  | { kind: "shift" | "night"; key: string; staffId: string; name: string; time: string; shiftId?: string; note?: string }
  | { kind: "leave"; key: string; staffId: string; name: string; overrideId: string }
  | { kind: "gap"; key: string };
export interface DutyRow { duty: string; label: string; people: string[]; cells: CellItem[][] }

/** One row per duty that has a shift or a person, one cell per day. Leave hides that person's shift for the day; a swap
 *  shows the cover instead; an extra shift is added. A day with nobody for a duty that works other days is a gap. */
export function buildWeek(monday: string, patterns: ShiftPattern[], overrides: ShiftOverride[], staff: OpsStaff[], tz = WORKSPACE_TZ): DutyRow[] {
  const byId = new Map(staff.map(s => [s.id, s]));
  const name = (id: string) => byId.get(id)?.name ?? "Someone who left";
  const dates = weekDates(monday);
  const live = patterns.filter(p => p.active);
  const duties = DUTY_ORDER.filter(d => live.some(p => p.duty === d) || staff.some(s => s.active && s.duties.some(x => x.duty === d)));
  return duties.map(duty => {
    const cells = dates.map((iso, wd) => {
      const day = overrides.filter(o => covers(o, iso, tz));
      const items: CellItem[] = [];
      for (const p of live.filter(x => x.duty === duty && x.weekday === wd).sort((a, b) => a.start_minute - b.start_minute)) {
        const off = day.find(o => o.staff_id === p.staff_id && (o.kind === "leave" || o.kind === "swap"));
        const time = `${hhmm(p.start_minute)}-${hhmm(p.end_minute)}`;
        const kind = isNight(p) ? "night" : "shift";
        if (off) items.push({ kind: "leave", key: `${p.id}-l`, staffId: p.staff_id, name: name(p.staff_id), overrideId: off.id });
        if (off?.kind === "swap" && off.replacement_staff_id) {
          items.push({ kind, key: `${p.id}-s`, staffId: off.replacement_staff_id, name: name(off.replacement_staff_id), time, note: `covering ${name(p.staff_id)}` });
        } else if (!off) items.push({ kind, key: p.id, staffId: p.staff_id, name: name(p.staff_id), time, shiftId: p.id });
      }
      for (const o of day.filter(x => x.kind === "extra" && x.duty === duty)) {
        const start = localDate(o.starts_at, tz) === iso ? localMinute(o.starts_at, tz) : 0;
        const end = localDate(o.ends_at, tz) === iso ? localMinute(o.ends_at, tz) : 1440;
        items.push({ kind: "shift", key: `${o.id}-x`, staffId: o.staff_id, name: name(o.staff_id), time: `${hhmm(start)}-${hhmm(end)}`, note: "extra shift" });
      }
      const worksSomeDay = live.some(p => p.duty === duty);
      if (worksSomeDay && !items.some(i => i.kind !== "leave")) items.push({ kind: "gap", key: `${duty}-${wd}-gap` });
      return items;
    });
    const people = [...new Set(live.filter(p => p.duty === duty).map(p => name(p.staff_id)))];
    return { duty, label: DUTY_LABELS[duty] ?? duty, people, cells };
  });
}

export const countGaps = (rows: DutyRow[], day?: number) =>
  rows.reduce((n, r) => n + r.cells.filter((c, i) => (day == null || i === day) && c.some(x => x.kind === "gap")).length, 0);

// ── If nobody answers ──────────────────────────────────────────────────────

export const isOwnerStep = (s: ChainSpec) => s.type === "role" && s.role === "owner";

/** When each step is alerted if nobody taps Acknowledge: the first step that reaches someone goes at once, each later one
 *  `ack` minutes after the one before; a step with nobody to reach is skipped at once (roster_service.first_step_with_recipients). */
export function chainTimes(steps: Pick<OnDutyStep, "recipients">[], ack: number): (number | null)[] {
  let t = -1;
  return steps.map(s => {
    if (!s.recipients.length) return null;
    t = t < 0 ? 0 : t + ack;
    return t;
  });
}

export function stepWords(s: ChainSpec, duty: string, staffName: (id: string) => string | undefined): string {
  const dutyWord = (DUTY_LABELS[s.duty ?? duty] ?? s.duty ?? duty).toLowerCase();
  if (s.type === "on_shift") return s.duty && s.duty !== duty ? `${DUTY_LABELS[s.duty] ?? s.duty} on shift` : `Whoever is on shift (${dutyWord})`;
  if (s.type === "duty") return `Anyone who does ${dutyWord}, as backup`;
  if (s.type === "staff") return staffName(s.staff_id ?? "") ?? "A person who left";
  return s.role === "owner" ? "Owner" : s.role === "manager" ? "Managers" : `Everyone with the ${s.role} role`;
}

/** The steps a person edits: every step except the owner, who the server always keeps last. */
export const editableSteps = (steps: ChainSpec[]) => steps.filter(s => !isOwnerStep(s));
/** What PUT /ops/escalation-chains gets: the edited steps, then the owner (the default keeps "owner last"). */
export const withOwnerLast = (steps: ChainSpec[]): ChainSpec[] => [...editableSteps(steps), { type: "role", role: "owner" }];
export function moveStep<T>(list: T[], i: number, by: -1 | 1): T[] {
  const j = i + by;
  if (j < 0 || j >= list.length) return list;
  const next = [...list];
  [next[i], next[j]] = [next[j], next[i]];
  return next;
}
