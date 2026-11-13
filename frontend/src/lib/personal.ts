// Personal call workspace (backend services/personal_calls.py, endpoints/personal_calls.py): types and plain-language
// formatting for the Calls and Reminders screens. Times read in the workspace timezone (IST).

export type CallStatus = "ready" | "analysing" | "transcribing" | "too_short" | "no_recording" | "failed";

export interface CallRow {
  id: string;
  at: string | null;
  direction: "in" | "out";
  contact: string;
  number: string;
  duration_sec: number;
  status: CallStatus;
  title: string | null;
  category: string | null;
  reminders_open: number;
}

export interface Upcoming {
  what: string;
  date: string;
  time: string;
  place: string;
  call_id: string;
  contact: string;
}

export interface ActionItem {
  id: string;
  text: string;
  owner: string;
  due: string;
  context: string;
  done: boolean;
  done_at: string | null;
}

export interface Memory {
  title: string;
  category: string;
  tags: string[];
  participants: { name: string; role: string }[];
  decision: string;
  sections: { heading: string; bullets: string[] }[];
  action_items: ActionItem[];
  open_points: string[];
  upcoming: Omit<Upcoming, "call_id" | "contact">[];
  learning: string;
}

export interface CallDetail extends CallRow {
  memory: Memory | null;
  recording_url: string | null;
  transcript: { speaker: string; text: string; t0: number }[];
  share_text: string | null;
}

export interface Reminder extends ActionItem {
  call_id: string;
  call_title: string | null;
  call_at: string | null;
  contact: string;
}

export interface CallsPage {
  calls: CallRow[];
  has_more: boolean;
  upcoming?: Upcoming[];
}

const TZ = "Asia/Kolkata";

/** YYYY-MM-DD of a moment, in IST. */
export function istDay(d: Date): string {
  return d.toLocaleDateString("en-CA", { timeZone: TZ });
}

function addDays(day: string, n: number): string {
  const d = new Date(`${day}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

/** "Today", "Yesterday", or "Wed, 12 Nov" (with the year when it is not this year). */
export function dayLabel(day: string, now: Date = new Date()): string {
  const today = istDay(now);
  if (day === today) return "Today";
  if (day === addDays(today, -1)) return "Yesterday";
  if (day === addDays(today, 1)) return "Tomorrow";
  const d = new Date(`${day}T00:00:00Z`);
  const sameYear = day.slice(0, 4) === today.slice(0, 4);
  return d.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", ...(sameYear ? {} : { year: "numeric" }), timeZone: "UTC" });
}

export function timeLabel(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit", timeZone: TZ }).toLowerCase();
}

export function durationLabel(sec: number): string {
  if (!sec) return "0 s";
  if (sec < 60) return `${sec} s`;
  const m = Math.round(sec / 60);
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`;
}

/** Due date in words, and whether it is past. "" = no date. */
export function dueLabel(due: string, now: Date = new Date()): { text: string; overdue: boolean } {
  if (!due) return { text: "", overdue: false };
  const today = istDay(now);
  const label = dayLabel(due, now);
  const word = label === "Today" || label === "Tomorrow" || label === "Yesterday" ? label.toLowerCase() : label;
  return due < today ? { text: `Was due ${word}`, overdue: true } : { text: `Due ${word}`, overdue: false };
}

export function ownerLabel(owner: string): string {
  return !owner || owner.toLowerCase() === "me" ? "You" : owner;
}

export function isMine(owner: string): boolean {
  return !owner || owner.toLowerCase() === "me";
}

export const STATUS_TEXT: Record<CallStatus, string> = {
  ready: "",
  analysing: "Writing the summary",
  transcribing: "Transcribing the recording",
  too_short: "Too short to summarise",
  no_recording: "No recording",
  failed: "Couldn't summarise this call",
};

/** Group rows by IST day, newest day first (rows arrive newest first). */
export function groupByDay<T extends { at: string | null }>(rows: T[]): { day: string; rows: T[] }[] {
  const groups: { day: string; rows: T[] }[] = [];
  for (const r of rows) {
    const day = r.at ? istDay(new Date(r.at)) : "";
    const last = groups[groups.length - 1];
    if (last && last.day === day) last.rows.push(r);
    else groups.push({ day, rows: [r] });
  }
  return groups;
}
