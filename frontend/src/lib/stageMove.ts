// Stage moves, shared by every place that changes a lead's stage (lead page StageSheet, Leads list select, Inbox guest panel).
// The backend decides (inquiry_service: a move back or out of Lost needs an owner/manager + a reason, Sold stays Sold);
// these helpers only ask for the reason up front and show the backend's own words when it says no.

type Stage = { order: number; is_closed_won: boolean; is_closed_lost: boolean };

/** "reopen" = out of Lost into an open stage, "back" = to an earlier open stage; both need a reason. */
export function reasonNeeded(current: Stage | undefined, target: Stage): "reopen" | "back" | null {
  if (!current || target.is_closed_won || target.is_closed_lost) return null;
  if (current.is_closed_lost) return "reopen";
  if (!current.is_closed_won && target.order < current.order) return "back";
  return null;
}

/** The backend's message: a plain `detail`, a `{message}` detail (outcome_reason_required), or an Error's text. */
export function stageErrorText(e: unknown, fallback: string): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof d === "string" && d) return d;
  const m = (d as { message?: unknown } | undefined)?.message;
  if (typeof m === "string" && m) return m;
  if (e instanceof Error && e.message && !(e as { response?: unknown }).response) return e.message;
  return fallback;
}

/** Native prompt for the two compact selects (Leads list, Inbox panel). null = cancelled or empty. */
export function askReason(kind: "reopen" | "back", label: string): string | null {
  const q = kind === "reopen"
    ? `Reopen this lost lead into ${label}? Only an owner or manager can. Why?`
    : `Move back to ${label}? Only an owner or manager can. Why?`;
  const r = window.prompt(q)?.trim();
  return r ? r : null;
}
