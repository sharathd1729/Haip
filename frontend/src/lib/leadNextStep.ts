// The ONE next step for a lead, derived from its stage and the facts in its thread. The lead page's pinned bar, the
// summary card and every CTA read this, so they can never disagree (the old page showed an AI summary saying
// "marked lost" next to a stage of "new"). Pure: no fetching, no clock unless `now` is passed. Tested in
// leadNextStep.test.ts. The AI's own next_action is NOT an input: it is prose written at summary time and can be stale.

export type NextStepAction = "call" | "message" | "quote" | "book" | "open_booking" | "review_draft" | "stage";
export type NextStepTone = "urgent" | "normal" | "done";

export interface NextStepStage {
  key?: string | null;
  label?: string | null;
  category?: string | null;      // valid | invalid | marketing
  is_closed_won?: boolean;
  is_closed_lost?: boolean;
}

export interface NextStepFacts {
  name: string;                               // first name or display name, for the sentence
  stage: NextStepStage;
  hasPhone: boolean;
  lastInboundAt?: string | null;
  lastOutboundAt?: string | null;
  unansweredOutboundCalls?: number;
  missedInboundUnreturned?: boolean;
  pendingDrafts?: number;
  lostReason?: string | null;
  /** The newest live quote (issued / waiting for approval / accepted), if any. */
  openQuote?: { amount: number; validUntil?: string | null; sharedVia?: string | null; status?: string | null } | null;
  /** A booking of this lead (not a cancelled one). */
  booking?: { id: string; outstanding?: number | null; checkIn?: string | null } | null;
  now?: Date;
}

export interface NextStep {
  key: string;
  title: string;
  why: string;
  tone: NextStepTone;
  actions: NextStepAction[];     // first one is the primary button
}

const H = 3_600_000;
const inr = (n: number) => `₹${Math.round(n).toLocaleString("en-IN")}`;
const t = (iso?: string | null) => (iso ? new Date(iso).getTime() : NaN);

export const LOST_REASON_LABEL: Record<string, string> = {
  wrong_dates: "Dates did not work", weather_concern: "Weather", budget_mismatch: "Price too high",
  couldnt_decide: "Couldn't decide", chose_competitor: "Booked somewhere else", no_response: "No response",
  capacity: "Group too big", other: "Other",
};

function relDay(iso: string, now: Date): string {
  const d = new Date(iso);
  const opts: Intl.DateTimeFormatOptions = { timeZone: "Asia/Kolkata" };
  const day = (x: Date) => x.toLocaleDateString("en-CA", opts);
  const time = d.toLocaleTimeString("en-IN", { ...opts, hour: "numeric", minute: "2-digit" });
  if (day(d) === day(now)) return `today ${time}`;
  if (day(d) === day(new Date(now.getTime() + 24 * H))) return `tomorrow ${time}`;
  return `${d.toLocaleDateString("en-IN", { ...opts, weekday: "short", day: "numeric", month: "short" })}, ${time}`;
}

const withPhone = (f: NextStepFacts, actions: NextStepAction[]) => actions.filter(a => a !== "call" || f.hasPhone);

export function deriveNextStep(f: NextStepFacts): NextStep {
  const now = f.now ?? new Date();
  const name = f.name || "them";
  const s = f.stage;
  const key = (s.key || "").toLowerCase();

  if (s.is_closed_lost || key === "lost") {
    const why = f.lostReason ? `Reason: ${LOST_REASON_LABEL[f.lostReason] ?? f.lostReason}.` : "No reason was recorded.";
    return { key: "closed_lost", title: "Closed as lost — nothing to do", tone: "done", actions: [],
      why: `${why} Reminders are off. If ${name} writes again you will see it in My day.` };
  }
  if (key === "unsuitable") {
    return { key: "unsuitable", title: "Marked unsuitable — no follow-up needed", tone: "done", actions: [],
      why: `If ${name} writes again you will see it in My day.` };
  }

  if (f.booking) {
    const due = f.booking.outstanding ?? 0;
    if (due > 0) {
      return { key: "collect_payment", title: `Collect ${inr(due)} still due`, tone: "urgent", actions: ["open_booking", "message"],
        why: `${name} is booked. Send the payment link from the booking so the dates stay held.` };
    }
    return { key: "booked", title: "Booked — nothing due", tone: "done", actions: ["open_booking"],
      why: "The booking is paid. Use the booking page for the trip details and the handover." };
  }
  if (s.is_closed_won) {
    return { key: "add_booking", title: "Add the booking", tone: "urgent", actions: ["book"],
      why: `The lead is marked ${s.label || "Sold"} but no booking is linked to it yet.` };
  }

  if (f.missedInboundUnreturned) {
    return { key: "call_back", title: `Call ${name} back`, tone: "urgent", actions: withPhone(f, ["call", "message"]),
      why: `${name} called and nobody answered. Nobody has called back since.` };
  }
  if ((f.pendingDrafts ?? 0) > 0) {
    return { key: "review_draft", title: "Review the AI reply and send it", tone: "urgent", actions: ["review_draft", "message"],
      why: `An AI draft for ${name} is waiting for a person. Nothing has been sent.` };
  }
  const lastIn = t(f.lastInboundAt);
  const lastOut = t(f.lastOutboundAt);
  if (Number.isFinite(lastIn) && (!Number.isFinite(lastOut) || lastIn > lastOut)) {
    return { key: "reply", title: `Reply to ${name}`, tone: "urgent", actions: withPhone(f, ["message", "call"]),
      why: `${name} wrote ${relDay(f.lastInboundAt!, now)} and has not had an answer.` };
  }
  if (!f.hasPhone) {
    return { key: "ask_number", title: `Ask ${name} for a phone number`, tone: "normal", actions: ["message"],
      why: "Without a number this is a chat, not a lead: no call, no quote on WhatsApp." };
  }

  const q = f.openQuote;
  if (q) {
    const exp = t(q.validUntil);
    if (Number.isFinite(exp) && exp < now.getTime()) {
      return { key: "quote_expired", title: "The quote has expired — send a fresh one", tone: "urgent", actions: withPhone(f, ["quote", "call"]),
        why: `The ${inr(q.amount)} quote ran out ${relDay(q.validUntil!, now)}.` };
    }
    if (q.status === "pending_approval") {
      return { key: "quote_waiting", title: "The quote is waiting for the owner's OK", tone: "normal", actions: withPhone(f, ["call"]),
        why: `${inr(q.amount)} is drafted. It goes to ${name} once it is approved.` };
    }
    if (!q.sharedVia) {
      return { key: "send_quote", title: `Send the ${inr(q.amount)} quote`, tone: "urgent", actions: withPhone(f, ["quote", "call"]),
        why: "It was saved but never sent or copied." };
    }
    if (Number.isFinite(exp) && exp - now.getTime() < 24 * H) {
      return { key: "quote_expiring", title: "Follow up before the quote expires", tone: "urgent", actions: withPhone(f, ["call", "message"]),
        why: `The ${inr(q.amount)} quote is valid until ${relDay(q.validUntil!, now)}.` };
    }
    if ((f.unansweredOutboundCalls ?? 0) >= 2) {
      return { key: "no_answer", title: `No answer after ${f.unansweredOutboundCalls} calls — send a WhatsApp`, tone: "normal",
        actions: withPhone(f, ["message", "call"]), why: `The ${inr(q.amount)} quote is with ${name}.` };
    }
    return { key: "follow_up_quote", title: `Follow up on the ${inr(q.amount)} quote`, tone: "normal", actions: withPhone(f, ["call", "message"]),
      why: q.validUntil ? `Sent; valid until ${relDay(q.validUntil, now)}.` : "Sent; ask if it works for them." };
  }

  if ((f.unansweredOutboundCalls ?? 0) >= 2) {
    return { key: "no_answer", title: `No answer after ${f.unansweredOutboundCalls} calls — send a WhatsApp`, tone: "normal",
      actions: withPhone(f, ["message", "call"]), why: "Leave a message they can answer when it suits them." };
  }
  if (s.category === "invalid" || key === "general_enquiry" || key === "rnr") {
    return { key: "qualify", title: key === "rnr" ? `Try ${name} once more` : `Call ${name} to qualify`, tone: "normal",
      actions: withPhone(f, ["call", "stage"]), why: "Confirm the dates, group size and pickup, then move the lead to Active." };
  }
  return { key: "send_quote_new", title: `Send ${name} a quote`, tone: "normal", actions: withPhone(f, ["quote", "call"]),
    why: "No quote has gone out on this lead yet." };
}

export type Temperature = { label: "Hot" | "Warm" | "Cold" | "Won" | "Closed"; tone: "danger" | "warning" | "info" | "success" | "neutral" };

/** One word for how warm the lead is, from the same facts: stage first, then how recently they wrote. */
export function leadTemperature(f: Pick<NextStepFacts, "stage" | "lastInboundAt" | "booking" | "now">): Temperature {
  const s = f.stage;
  if (s.is_closed_lost || s.key === "lost" || s.key === "unsuitable") return { label: "Closed", tone: "neutral" };
  if (s.is_closed_won || f.booking) return { label: "Won", tone: "success" };
  const age = ((f.now ?? new Date()).getTime() - t(f.lastInboundAt)) / H;
  if (Number.isFinite(age) && age <= 48) return { label: "Hot", tone: "danger" };
  if (Number.isFinite(age) && age <= 24 * 7) return { label: "Warm", tone: "warning" };
  return { label: "Cold", tone: "info" };
}
