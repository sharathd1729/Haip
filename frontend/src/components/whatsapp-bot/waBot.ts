// WhatsApp hours and welcome (GET/PUT /whatsapp/bot-settings, backend services/wa_bot_settings.py): types + pure helpers.

export const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;
export type DayKey = (typeof DAYS)[number];
export const DAY_NAME: Record<DayKey, string> = { mon: "Monday", tue: "Tuesday", wed: "Wednesday", thu: "Thursday", fri: "Friday", sat: "Saturday", sun: "Sunday" };

export type Day = { closed: boolean; open: string; close: string };
export type Holiday = { date: string; label: string };
export type Hours = { weekly: Record<DayKey, Day>; holidays: Holiday[] };
export type Welcome = { enabled: boolean; text: string; buttons: string[]; also_when_ai_replies: boolean };
export type LocationReply = { enabled: boolean; text: string; map_link: string };
export type OptConfirm = { custom: boolean; stop_text: string; start_text: string };
export type Sections = { hours: Hours; welcome: Welcome; location_reply: LocationReply; opt_confirm: OptConfirm };
export type BotSettings = Sections & { timezone: string; hours_summary: string; open_now: boolean };

/** What the guest sees: {first_name} filled with an example name. */
export function fillPreview(text: string, firstName = "Ananya"): string {
  return text.replaceAll("{first_name}", firstName);
}

export function locationPreview(l: LocationReply): string {
  return fillPreview(l.text) + (l.map_link.trim() ? `\n${l.map_link.trim()}` : "");
}

/** Add (or relabel) one holiday; one per date, oldest first. A blank date is ignored. */
export function addHoliday(list: Holiday[], date: string, label: string): Holiday[] {
  if (!date) return list;
  return [...list.filter(h => h.date !== date), { date, label: label.trim().slice(0, 40) }].sort((a, b) => a.date.localeCompare(b.date));
}

/** "Same as Monday" for every day. */
export function copyToAll(weekly: Record<DayKey, Day>, from: DayKey): Record<DayKey, Day> {
  return Object.fromEntries(DAYS.map(d => [d, { ...weekly[from] }])) as Record<DayKey, Day>;
}

/** Meta's limits for reply buttons: at most 3, 20 characters each, all different. */
export function buttonProblem(buttons: string[]): string | null {
  const b = buttons.map(x => x.trim()).filter(Boolean);
  if (b.length > 3) return "At most 3 buttons.";
  if (b.some(x => x.length > 20)) return "Keep each button to 20 characters.";
  if (new Set(b.map(x => x.toLowerCase())).size !== b.length) return "Each button needs different text.";
  return null;
}

/** Times run past midnight when closing is at or before opening (e.g. 18:00 to 02:00). */
export function dayHint(d: Day): string {
  if (d.closed) return "Closed all day";
  if (d.open === d.close) return "Open all day";
  return d.close < d.open ? "Closes after midnight" : "";
}

/** Sections whose content differs from what was loaded (only those are sent). */
export function changedSections(saved: Sections, draft: Sections): Partial<Sections> {
  const keys = (["hours", "welcome", "location_reply", "opt_confirm"] as const).filter(k => JSON.stringify(saved[k]) !== JSON.stringify(draft[k]));
  return Object.fromEntries(keys.map(k => [k, draft[k]])) as Partial<Sections>;
}
