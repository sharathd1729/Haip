// What to offer under a message that did not go, read from the plain reason the backend stores
// (backend/app/services/wa_delivery_errors.py writes "... (Meta 131026)"; keep the codes in step with its REASONS).
// "retry" = sending the same message again can work; "template" = WhatsApp's 24-hour window is closed;
// "whatsapp" = Instagram's window is closed, so reach the guest's number on WhatsApp; "none" = the reason says what to do.
export type FailureStep = "retry" | "template" | "whatsapp" | "none";

const NEEDS_TEMPLATE = /\(Meta 131047\)|24-hour WhatsApp window/i;
const INSTAGRAM_WINDOW = /outside of allowed window|allowed window|2534022|24-hour Instagram window/i;
const NO_RETRY = /\(Meta (131026|131049|131050|130472|131042|131031|132000|132001|132012)\)|isn't a valid WhatsApp number|has no phone number/i;

export function failureStep(error?: string | null, opts: { isTemplate?: boolean; channel?: string } = {}): FailureStep {
  const e = error ?? "";
  if (NEEDS_TEMPLATE.test(e)) return "template";
  if (opts.channel === "instagram" && INSTAGRAM_WINDOW.test(e)) return "whatsapp";
  if (opts.isTemplate || NO_RETRY.test(e)) return "none";
  return "retry";
}
