/**
 * Frontend mirror of backend inquiry state-machine (inquiry_service.py).
 * Kept in sync manually — the backend is the authority and will reject invalid moves.
 */

export type InquiryStage =
  | "new"
  | "responding"
  | "quoted"
  | "site_visit"
  | "booked"
  | "lost"
  | "ghosted";

const EXIT_STAGES: Set<InquiryStage> = new Set(["lost", "ghosted"]);

const ALLOWED_FORWARD: Record<InquiryStage, InquiryStage[]> = {
  new:        ["responding"],
  responding: ["quoted"],
  quoted:     ["site_visit", "booked"],
  site_visit: ["booked"],
  booked:     [],
  lost:       [],
  ghosted:    [],
};

const STAGE_RANK: Partial<Record<InquiryStage, number>> = {
  new: 0, responding: 1, quoted: 2, site_visit: 3, booked: 4,
};

export type TransitionResult =
  | { allowed: true;  direction: "forward" | "exit" }
  | { allowed: false; reason: "terminal" | "not_allowed" }
  | { allowed: "backward"; direction: "backward" };

export function canTransition(from: InquiryStage, to: InquiryStage): TransitionResult {
  if (from === to) return { allowed: true, direction: "forward" };
  if (EXIT_STAGES.has(from)) return { allowed: false, reason: "terminal" };
  if (EXIT_STAGES.has(to))   return { allowed: true, direction: "exit" };

  if (ALLOWED_FORWARD[from]?.includes(to)) return { allowed: true, direction: "forward" };

  const fromRank = STAGE_RANK[from];
  const toRank   = STAGE_RANK[to];
  if (fromRank !== undefined && toRank !== undefined && toRank < fromRank) {
    return { allowed: "backward", direction: "backward" };
  }

  return { allowed: false, reason: "not_allowed" };
}

/** All stages a card can legally be dropped onto (allowed forward + exit, not terminal). */
export function allowedDropTargets(from: InquiryStage): InquiryStage[] {
  return (Object.keys(ALLOWED_FORWARD) as InquiryStage[]).filter(to => {
    if (to === from) return false;
    const r = canTransition(from, to);
    return r.allowed === true || r.allowed === "backward";
  });
}
