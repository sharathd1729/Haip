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
  /** Where on the call it was said (Reminders page; on a memory it is `refs[refKey(text)]`). */
  ref?: Ref | null;
}

/** A source: the words on the call a point came from and the second they start (null = not timed). */
export interface Ref { at: number | null; quote: string }

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
  /** Fields the person corrected (field -> when); a re-read by Yaad keeps them. */
  edited?: Record<string, string>;
  history?: MemoryChange[];
  /** Point text key (refKey) -> where on the call it was said. */
  refs?: Record<string, Ref>;
}

export interface MemoryChange {
  id: string;
  at: string;
  by: string;
  fields: string[];
  before: Partial<Memory>;
  after: Partial<Memory>;
  undo_of?: string;
}

/** What PATCH /me/calls/{id}/memory takes: any of these, only the ones that changed. */
export type MemoryPatch = Partial<Pick<Memory,
  "title" | "category" | "tags" | "participants" | "decision" | "sections" | "open_points" | "upcoming" | "learning">> & {
  action_items?: (Partial<ActionItem> & { text: string })[];
};

export const CATEGORIES = ["Business", "Networking", "Family", "Personal", "Health", "Travel", "Finance", "Other"] as const;

/** Plain words for a changed field in the history list. */
export const FIELD_LABEL: Record<string, string> = {
  title: "Title", category: "Category", tags: "Tags", participants: "People", decision: "Decision", sections: "Summary",
  action_items: "Tasks", open_points: "Still open", upcoming: "Coming up", learning: "Worth remembering",
};

export interface Folder {
  id: string;
  name: string;
  color: string;
  keywords: string[];
  prompt: string;
  count?: number;
}

/** Folder colours: CSS tokens --y-folder-<key> in globals.css (.yaad). */
export const FOLDER_COLORS = ["mango", "tomato", "leaf", "sky", "plum", "stone"] as const;
export const folderColor = (c: string) => `var(--y-folder-${(FOLDER_COLORS as readonly string[]).includes(c) ? c : "mango"})`;

export interface CalEvent {
  id: string;
  title: string;
  day: string;               // YYYY-MM-DD
  start_time: string | null; // HH:MM, null = all day
  place: string;
  notes: string;
  people: { name: string; role: string }[];
  status: "suggested" | "accepted" | "dismissed";
  call_id: string | null;
  google: boolean;
  google_synced: boolean;
  google_error: string | null;
  /** The moment on the call this plan was said (suggestions from calls). */
  source?: Ref | null;
}

/** The 6-week grid (Mon first) that shows `month` (YYYY-MM): 42 YYYY-MM-DD days. */
export function monthGrid(month: string): string[] {
  const first = new Date(`${month}-01T00:00:00Z`);
  const back = (first.getUTCDay() + 6) % 7;
  return Array.from({ length: 42 }, (_, i) => addDays(`${month}-01`, i - back));
}

export function shiftMonth(month: string, by: number): string {
  const d = new Date(`${month}-01T00:00:00Z`);
  d.setUTCMonth(d.getUTCMonth() + by);
  return d.toISOString().slice(0, 7);
}

export interface CallDetail extends CallRow {
  folders?: Pick<Folder, "id" | "name" | "color">[];
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

/** A Google Calendar "new event" link, prefilled (no sign-in to Yaad needed; Google asks the person to save it).
 *  With a time: a one-hour event in IST. Without: an all-day event. */
export function calendarLink(e: { title: string; date: string; time?: string; place?: string; details?: string }): string {
  const ymd = e.date.replace(/-/g, "");
  let dates: string;
  if (e.time && /^\d{2}:\d{2}$/.test(e.time)) {
    const [h, m] = e.time.split(":").map(Number);
    const end = `${String(Math.min(h + 1, 23)).padStart(2, "0")}${String(h + 1 > 23 ? 59 : m).padStart(2, "0")}`;
    dates = `${ymd}T${e.time.replace(":", "")}00/${ymd}T${end}00`;
  } else {
    dates = `${ymd}/${addDays(e.date, 1).replace(/-/g, "")}`;
  }
  const q = new URLSearchParams({ action: "TEMPLATE", text: e.title, dates, ctz: TZ });
  if (e.place) q.set("location", e.place);
  if (e.details) q.set("details", e.details);
  return `https://calendar.google.com/calendar/render?${q.toString()}`;
}

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

// ─── References ──────────────────────────────────────────────────────────────

/** Same key as the backend's personal_calls.ref_key: a point keeps its source only while its words are unchanged. */
export const refKey = (text: string) => text.toLowerCase().split(/\s+/).filter(Boolean).join(" ").slice(0, 400);

/** "0:42", "12:05", "1:02:09". */
export function momentLabel(sec: number): string {
  const s = Math.max(0, Math.floor(sec));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${r}` : `${m}:${r}`;
}

/** The memory page link that opens the call at that moment. */
export const momentHref = (callId: string, at?: number | null) =>
  `/dashboard/me/calls/${callId}${at != null ? `?t=${Math.floor(at)}` : ""}`;

/** Numbers for a memory's sourced points in reading order (decision, summary, tasks, still open, coming up). */
export function citeOrder(m: Pick<Memory, "decision" | "sections" | "action_items" | "open_points" | "upcoming" | "refs">): Map<string, number> {
  const order = new Map<string, number>();
  const texts = [m.decision, ...m.sections.flatMap(s => s.bullets), ...m.action_items.map(a => a.text), ...m.open_points, ...m.upcoming.map(u => u.what)];
  for (const t of texts) {
    const k = t ? refKey(t) : "";
    if (k && m.refs?.[k] && !order.has(k)) order.set(k, order.size + 1);
  }
  return order;
}

/** One source of an Ask Yaad answer: marker [n] -> the call, and the moment when Yaad found it. */
export interface AskSource { n: number; call_id: string; title: string | null; contact: string; at: string; t: number | null; quote: string | null }

export interface AskTurn { id: string; at: string; question: string; answer: string; sources: AskSource[]; followups: string[] }

export interface AskChat { id: string; title: string; folder_id: string | null; turns_count: number; updated_at: string | null; turns?: AskTurn[] }

/** Text split around [n] markers: strings and numbers, in order. */
export function splitCites(text: string): (string | number)[] {
  return text.split(/\[(\d{1,3})\]/g).map((part, i) => (i % 2 ? Number(part) : part)).filter(p => p !== "");
}

/** The answer without its markers (what goes to WhatsApp or the clipboard). */
export const withoutCites = (text: string) => text.replace(/ ?\[\d{1,3}\]/g, "");

/** Chat history groups: Today, Yesterday, Previous 7 days, then month names. */
export function chatGroup(iso: string | null, now: Date = new Date()): string {
  if (!iso) return "Older";
  const day = istDay(new Date(iso)), today = istDay(now);
  if (day === today) return "Today";
  if (day === addDays(today, -1)) return "Yesterday";
  if (day >= addDays(today, -7)) return "Previous 7 days";
  return new Date(iso).toLocaleDateString("en-IN", { month: "long", year: "numeric", timeZone: TZ });
}
