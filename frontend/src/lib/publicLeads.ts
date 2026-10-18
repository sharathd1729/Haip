// HAIP's own website forms (book-demo, contact, property assessment) -> POST /api/v1/public/leads.
// The old forms posted to /api/leads/* (no such route), swallowed the error and showed "success": every lead was lost.
// A form may show success ONLY when submitPublicLead() returns ok.

// Must match NOTICE_TEXTS["web-v1"] in backend/app/services/platform_lead_service.py. Never edit a version in place:
// add a new one on both sides.
export const NOTICE_VERSION = "web-v1";
export const NOTICE_TEXT =
  "HAIP will use your name, phone number and email to reply to this request and follow up about HAIP. " +
  "We keep it for up to 24 months and never sell it. You can ask us to correct or delete it at any time " +
  "on our grievance page.";

export const SUPPORT_WHATSAPP = "+91 81476 98153";

export type LeadKind = "demo" | "contact" | "assessment";

export interface PublicLeadBody {
  kind: LeadKind;
  submission_id: string;
  name: string;
  email?: string | null;
  phone?: string | null;
  company?: string | null;
  message?: string | null;
  details?: Record<string, string>;
  consent: boolean;
  marketing_opt_in?: boolean;
  notice_version?: string;
  website?: string; // honeypot
  assessment?: unknown;
}

export type SubmitResult<T> = { ok: true; data: T } | { ok: false; message: string };

/** One id per form fill, re-sent on retry, so a double click or a retry never makes two leads. */
export function newSubmissionId(): string {
  const c = typeof globalThis !== "undefined" ? globalThis.crypto : undefined;
  if (c && typeof c.randomUUID === "function") return c.randomUUID().replace(/-/g, "");
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`;
}

/** The message a visitor sees when the server did not accept the form. */
export function failureMessage(status: number, body: unknown): string {
  if (status === 429) return "Too many attempts from this connection. Please wait a little and try again.";
  if (status === 413) return "That message is too long. Please shorten it and try again.";
  if (status === 422) {
    const detail = (body as { detail?: unknown } | null)?.detail;
    if (typeof detail === "string" && detail) return detail;
    if (Array.isArray(detail) && detail.length) {
      const msg = String((detail[0] as { msg?: unknown })?.msg ?? "");
      if (msg) return msg.replace(/^Value error,\s*/i, "");
    }
    return "Please check the form and try again.";
  }
  return `We couldn't send this right now. Please try again, or WhatsApp us on ${SUPPORT_WHATSAPP}.`;
}

export async function postPublic<T>(path: string, body: unknown): Promise<SubmitResult<T>> {
  let res: Response;
  try {
    res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    return { ok: false, message: `You seem to be offline. Please try again, or WhatsApp us on ${SUPPORT_WHATSAPP}.` };
  }
  let json: unknown = null;
  try {
    json = await res.json();
  } catch {
    json = null;
  }
  if (res.ok) return { ok: true, data: json as T };
  return { ok: false, message: failureMessage(res.status, json) };
}

export interface LeadAccepted {
  id: string;
  kind: LeadKind;
  status: "received";
  duplicate: boolean;
}

export function submitPublicLead<T = LeadAccepted>(body: PublicLeadBody): Promise<SubmitResult<T>> {
  return postPublic<T>("/api/v1/public/leads", { notice_version: NOTICE_VERSION, ...body });
}
