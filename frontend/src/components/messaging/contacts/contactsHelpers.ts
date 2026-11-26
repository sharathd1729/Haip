// Pure helpers for the WhatsApp contacts page (lists, bulk actions, growth). Tested in contactsHelpers.test.ts.

export type BulkAction = "add_tag" | "remove_tag" | "add_to_list" | "remove_from_list" | "opt_out" | "enrol" | "export";

export interface ContactFilter {
  opted_in?: boolean;
  search?: string;
  list_id?: string;
  tag?: string;
}

/** What a bulk request applies to: the ticked rows, or everyone matching the page's filter. */
export function bulkTarget(selected: string[], allMatching: boolean, filter: ContactFilter): { ids: string[] } | { filter: ContactFilter } {
  return allMatching ? { filter } : { ids: selected };
}

export function plural(n: number, one = "contact", many = `${one}s`): string {
  return `${n.toLocaleString("en-IN")} ${n === 1 ? one : many}`;
}

/** The confirm button says exactly what will happen, with the count ("Opt out 12 contacts?"). */
export function confirmLabel(action: BulkAction, count: number, value?: string): string {
  const who = plural(count);
  switch (action) {
    case "add_tag": return `Tag ${who} "${value}"?`;
    case "remove_tag": return `Remove the tag "${value}" from ${who}?`;
    case "add_to_list": return `Add ${who} to "${value}"?`;
    case "remove_from_list": return `Take ${who} off "${value}"?`;
    case "opt_out": return `Opt out ${who}? They will stop getting campaigns.`;
    case "enrol": return `Start "${value}" for ${who}?`;
    case "export": return `Download ${who} as a spreadsheet?`;
  }
}

/** The toast after a bulk action, saying what actually changed ("Tagged 23 contacts"). */
export function resultToast(action: BulkAction, changed: number, selected: number, value?: string): string {
  const who = plural(changed);
  const same = selected - changed;
  const note = same > 0 ? ` (${plural(same)} already ${action === "opt_out" ? "opted out" : "had it"})` : "";
  switch (action) {
    case "add_tag": return `Tagged ${who} "${value}"${note}`;
    case "remove_tag": return `Removed "${value}" from ${who}`;
    case "add_to_list": return `Added ${who} to "${value}"${note}`;
    case "remove_from_list": return `Took ${who} off "${value}"`;
    case "opt_out": return `Opted out ${who}${note}`;
    case "enrol": return `Started "${value}" for ${who}`;
    case "export": return `Downloaded ${who}`;
  }
}

export interface EnrolResult {
  selected: number;
  enrolled: number;
  started: number;
  queued: boolean;
  batches: number;
  skipped: { opted_out: number; not_a_guest: number };
}

/** One sentence after "Start a drip", including who was left out and why. */
export function enrolToast(r: EnrolResult, flowName: string): string {
  const head = r.queued
    ? `"${flowName}" will start for ${plural(r.enrolled)} over the next ${plural(r.batches, "minute")}`
    : `Started "${flowName}" for ${plural(r.started)}`;
  const left: string[] = [];
  if (r.skipped.opted_out) left.push(`${plural(r.skipped.opted_out)} opted out`);
  if (r.skipped.not_a_guest) left.push(`${plural(r.skipped.not_a_guest)} not in your guest list yet`);
  return left.length ? `${head}. Skipped: ${left.join(", ")}.` : `${head}.`;
}

export interface GrowthDay { date: string; new: number; opted_out: number }

/** "28 Oct – 26 Nov" for the chart's period label. */
export function periodLabel(from: string, to: string): string {
  const f = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
  return `${f(from)} – ${f(to)}`;
}

/** Net change over the period: new contacts minus people who opted out. */
export function netGrowth(daily: GrowthDay[]): number {
  return daily.reduce((n, d) => n + d.new - d.opted_out, 0);
}
