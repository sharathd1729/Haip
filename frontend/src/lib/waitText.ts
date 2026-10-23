// How long someone has waited, said the way a phone row says it ("2d late", "due in 10m", "gone cold"), and the colour for it.
// The severity always comes from the server (work_queue_service.SLA_MINUTES), never recomputed here.
import type { Tone } from "@/components/ui/page";

export type Severity = "fresh" | "late" | "urgent" | "critical" | "stale";

export const SEVERITY_TONE: Record<Severity, Tone> = {
  fresh: "neutral", late: "warning", urgent: "danger", critical: "danger", stale: "neutral",
};

/** "45m", "3h", "2d"; a time in the future gives "in 20m". Empty when unknown. */
export function shortAgo(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return "";
  const m = Math.round((now - t) / 60000);
  const fmt = (x: number) => (x < 60 ? `${Math.max(1, x)}m` : x < 1440 ? `${Math.floor(x / 60)}h` : `${Math.floor(x / 1440)}d`);
  return m < 0 ? `in ${fmt(-m)}` : m < 1 ? "just now" : fmt(m);
}

/** The right-hand words on a work-queue row: past the target -> "2d late"; still inside it -> "5m"; a due date ahead ->
 *  "due in 20m"; cold -> "gone cold". */
export function waitText(since: string | null | undefined, severity: Severity, now = Date.now()): string {
  if (severity === "stale") return "gone cold";
  const a = shortAgo(since, now);
  if (!a) return "";
  if (a.startsWith("in ")) return `due ${a}`;
  return severity === "fresh" ? a : `${a} late`;
}
